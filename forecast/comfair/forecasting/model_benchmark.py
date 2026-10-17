"""F1: bounded validation benchmark, champion freeze, then locked test evaluation."""
import argparse
import csv
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
from time import perf_counter

import numpy as np

from .baselines import MODELS, forecast
from .data import BACKEND, History, load_forecasting_data, resolve_source_record
from .metrics import aggregate_metrics
from .models import candidates, fit_candidate, LIBRARIES
from .schemas import MEMBERS, TARGETS, canonical_json
from .selection import ValidationScore, improvements, select_champion
from .splits import SPLITS, split_metadata
from .training import FEATURE_NAMES, supervised_rows

ARTIFACTS = BACKEND / 'comfair/artifacts'
F0 = ARTIFACTS / 'forecasting'
# The original integrated code required M3/M4 optimisation artifacts as
# immutable checkpoints. Standalone F1 checks *only* the preceding F0 artifacts.
F0_REQUIRED = ("f0_data_audit.json", "f0_baselines.json", "f0_predictions.csv")
EXPECTED = {}


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def verify_inputs():
    runtime_path = F0 / "f0.runtime.json"
    if not runtime_path.exists():
        raise FileNotFoundError("Run F0 first: python -m comfair.forecasting.benchmark "
                                "--output-dir comfair/artifacts/forecasting")
    recorded = json.loads(runtime_path.read_text()).get("artifact_hashes", {})
    for name in F0_REQUIRED:
        if name not in recorded or not (F0/name).is_file():
            raise ValueError(f"Missing F0 reference or digest: {name}")
        if digest(F0/name) != recorded[name]:
            raise ValueError(f"F0 reference changed after baseline evaluation: {name}")
    audit = json.loads((F0 / "f0_data_audit.json").read_text())
    for source in audit["sources"].values():
        if digest(resolve_source_record(source)) != source["sha256"]:
            raise ValueError(f"F0 source changed: {source['path']}")
    return audit


def baseline_reference(split):
    # Selection calls this ONLY for validation. Test reference retrieval is later.
    key = {'validation': 'validation', 'test': 'test_descriptive_only'}[split]
    return json.loads((F0/'f0_baselines.json').read_text())[key]


def evaluate(dataset, target, split, model_id, fitted=None):
    predictions, actual = [], []
    diagnostics = {'clipping_count': 0, 'clipping_magnitude_kw_sum': 0., 'deterministic_zero_pv_count': 0}
    inference = 0.
    for o in split.origins:
        history = dataset.history(target, o)
        start = perf_counter()
        result = (fitted.forecast(history, provenance=dataset.provenance) if fitted else
                  forecast(history, target=target, model_id=model_id, zero_pv_members=dataset.zero_pv_members))
        inference += perf_counter()-start
        predictions.append(np.asarray([r.y_pred for r in result.predictions]).reshape(24, 9))
        # Evaluation truth is obtained only after the origin's prediction.
        actual.append(getattr(dataset, target)[o:o+24])
        for key in diagnostics:
            diagnostics[key] += result.diagnostics[key]
    owners = MEMBERS if target == 'load_kw' else tuple(i for i in MEMBERS if i not in dataset.zero_pv_members)
    return {'metrics': aggregate_metrics(actual, predictions, percentage_members=owners),
            'diagnostics': diagnostics, 'origin_count': len(split.origins)}, np.asarray(predictions), inference


def validation_entry(target, metadata, evaluation, fitted_count, warnings):
    m = evaluation['metrics']
    key = f'validation/{target}/{metadata["model_id"]}'
    return dict(metadata, target=target, split='validation',
                validation_mae=m['micro']['mae_kw'], validation_rmse=m['micro']['rmse_kw'],
                validation_wape_micro=m['micro']['wape'], validation_wape_macro=m['member_macro']['wape'],
                validation_smape=m['micro']['smape'], evaluation=evaluation,
                number_of_fitted_models=fitted_count, eligible_for_champion=True, warnings=warnings,
                training_runtime={'artifact': 'f1.runtime.json', 'key': key, 'field': 'training_seconds'},
                prediction_runtime={'artifact': 'f1.runtime.json', 'key': key, 'field': 'prediction_seconds'})


def write_predictions(path, dataset, predictions):
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['target','model_id','origin_t','target_t','horizon_step','member_id','y_pred','y_true','error','absolute_error'])
        for target in TARGETS:
            model_id, array = predictions[target]
            for j, o in enumerate(SPLITS[2].origins):
                for h in range(24):
                    for i in MEMBERS:
                        p, y = float(array[j,h,i-1]), float(getattr(dataset,target)[o+h,i-1])
                        writer.writerow([target,model_id,o,o+h,h+1,i,repr(p),repr(y),repr(p-y),repr(abs(p-y))])


def run_f1(output_dir, verify_against=None):
    started = perf_counter()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Fail on output reuse: preserves the first locked test and prevents silent overwrite.
    if any(output_dir.glob('f1*')):
        raise ValueError('Use a fresh F1 output directory; existing F1 results are immutable')
    audit = verify_inputs()
    protected = {str(p.relative_to(ARTIFACTS)): digest(p) for p in ARTIFACTS.glob('*.json')}
    protected['forecasting/f0.runtime.json'] = digest(F0/'f0.runtime.json')
    dataset, current_audit = load_forecasting_data()
    if current_audit['sources'] != audit['sources'] or current_audit['split_contract'] != audit['split_contract']:
        raise ValueError('Canonical data provenance or split changed')
    source = sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        source.update(path.name.encode()+b'\0'+path.read_bytes())
    provenance = {'sources': audit['sources'], 'f0_checkpoint': '2a9a935',
                  'forecasting_source_sha256': source.hexdigest(),
                  'requirements_sha256': digest(BACKEND.parent/'requirements.txt'),
                  'upstream_artifact_hashes': EXPECTED, 'protected_artifact_hashes': protected,
                  'python': platform.python_version(),
                  'libraries': {name: version(name) for name in sorted(set(LIBRARIES.values()) | {'numpy','scipy','pandas','threadpoolctl'})}}
    space = candidates()
    config = {'split': split_metadata(), 'horizon_hours':24, 'origin_cadence_hours':24,
              'seed':0, 'threads':1, 'device':'cpu', 'feature_names': list(FEATURE_NAMES),
              'candidate_grid': [c.metadata() for c in space],
              'training_supervised_origins': {'first':168,'last':5232,'count':212},
              'validation_origins': {'first':5256,'last':6984,'count':73},
              'training_policy': 'fit once on TRAIN; fixed coefficients; expanding observed history at every origin',
              'refit_policy': 'freeze first, then fit selected configuration once on TRAIN+VALIDATION',
              'feature_missingness': 'unobservable short lags -> NaN; train-only median imputer + missing indicators',
              'global_identity': 'fixed one-hot canonical members 1..9',
              'weather_features': 'none; no future realised weather interface',
              'model_persistence': 'configuration only; deterministic retraining, no pickle',
              'runtime_storage': 'references into f1.runtime.json; no measured times in canonical JSON',
              'test_policy': 'only frozen champions; repeat is reproduction, never reselection based on test'}
    runtimes, entries = {}, []
    validation_refs = baseline_reference('validation')
    for target in TARGETS:
        # No access to test values is passed into any fit call.
        history = dataset.history(target, SPLITS[0].stop)
        rows = supervised_rows(history)
        for model_id in MODELS:
            ev, _, elapsed = evaluate(dataset, target, SPLITS[1], model_id)
            if ev['metrics'] != validation_refs[model_id][target]['metrics']:
                raise ValueError('F0 validation baseline reproduction mismatch')
            meta = {'model_id':model_id,'model_family':'naive','local_or_global':'local',
                    'direct_or_recursive':'direct','feature_set':'F0 historical target',
                    'hyperparameters':{},'seed':0,'threads':1,'library':'F0','library_version':'F0-v1',
                    'preprocessing':'none'}
            entries.append(validation_entry(target, meta, ev, 0, []))
            runtimes[f'validation/{target}/{model_id}'] = {'training_seconds':0.,'prediction_seconds':elapsed,'family':'naive'}
        for candidate in space:
            fitted = fit_candidate(candidate, history, target, dataset.zero_pv_members, rows=rows)
            ev, _, elapsed = evaluate(dataset, target, SPLITS[1], candidate.model_id, fitted)
            entries.append(validation_entry(target, candidate.metadata(), ev, len(fitted.models), fitted.warnings))
            runtimes[f'validation/{target}/{candidate.model_id}'] = {
                'training_seconds':fitted.training_runtime,'prediction_seconds':elapsed,'family':candidate.family}
            print(f'validation {target} {candidate.model_id}: macro WAPE={ev["metrics"]["member_macro"]["wape"]:.8f}', flush=True)
    champions = {}
    for target in TARGETS:
        group = [e for e in entries if e['target'] == target]
        refs = {e['model_id']: e['validation_wape_macro'] for e in group if e['model_id'] in MODELS}
        scores = []
        for e in group:
            e['baseline_improvements'] = improvements(e['validation_wape_macro'], refs)
            rt = runtimes[f'validation/{target}/{e["model_id"]}']
            scores.append(ValidationScore(e['model_id'], e['validation_wape_macro'], e['validation_mae'],
                                         rt['training_seconds']+rt['prediction_seconds'], e['number_of_fitted_models']))
        selected, trace = select_champion(scores)
        for row in trace['scores']:
            row['runtime_reference'] = f'f1.runtime.json#validation/{target}/{row["model_id"]}'
        champions[target] = {'configuration': next(e for e in group if e['model_id']==selected),
                             'selection_trace': trace, 'validation_only_selection':True,
                             'refit_policy':config['refit_policy'], 'test_metrics_accessed':False}
    entries.sort(key=lambda e: (e['target'], e['validation_wape_macro'], e['model_id']))
    leaderboard = {'schema_version':1,'milestone':'F1','split':'validation','provenance':provenance,
                   'configuration':config,'candidate_count':len(entries),'entries':entries}
    freeze = {'schema_version':1,'provenance':provenance,'champions':champions,
              'frozen_before_test':True, 'validation_only_selection':True}
    for name, data in (('f1_leaderboard.json', leaderboard), ('f1_champions.json', freeze)):
        encoded = canonical_json(data)
        if verify_against and encoded != (Path(verify_against)/name).read_text():
            raise ValueError(f'Reproduction differs before test: {name}')
        (output_dir/name).write_text(encoded)
    freeze_hash = digest(output_dir/'f1_champions.json')
    print('Champions frozen; unlocking official test for selected configurations only.', flush=True)
    # Test references are deliberately fetched only AFTER both champions are frozen on disk.
    test_refs = baseline_reference('test')
    tests, test_predictions = {}, {}
    for target in TARGETS:
        model_id = champions[target]['configuration']['model_id']
        fitted = None
        if model_id not in MODELS:
            candidate = next(c for c in space if c.model_id == model_id)
            fitted = fit_candidate(candidate, dataset.history(target, SPLITS[1].stop), target, dataset.zero_pv_members)
        ev, pred, elapsed = evaluate(dataset, target, SPLITS[2], model_id, fitted)
        runtimes[f'test/{target}/{model_id}'] = {'training_seconds':fitted.training_runtime if fitted else 0.,
                                                'prediction_seconds':elapsed,'family':fitted.candidate.family if fitted else 'naive'}
        refs = {name:test_refs[name][target]['metrics']['member_macro']['wape'] for name in MODELS}
        tests[target] = {'model_id':model_id,'evaluation':ev,
                         'baseline_references':{name:test_refs[name][target] for name in MODELS},
                         'baseline_improvements':improvements(ev['metrics']['member_macro']['wape'],refs),
                         'refit_range':{'start':0,'stop_exclusive':7008} if fitted else None,
                         'number_of_fitted_models':len(fitted.models) if fitted else 0,
                         'warnings':fitted.warnings if fitted else [],
                         'runtime_reference':f'f1.runtime.json#test/{target}/{model_id}',
                         'no_test_guided_reselection':True}
        test_predictions[target] = (model_id, pred)
    prediction_path = output_dir/'f1_test_predictions.csv'
    write_predictions(prediction_path, dataset, test_predictions)
    test_data = {'schema_version':1,'split':'test','provenance':provenance,'results':tests,
                 'champion_freeze_sha256':freeze_hash,'no_test_guided_reselection':True,
                 'predictions':{'file':prediction_path.name,'sha256':digest(prediction_path),
                                'rows':31536,'order':'target(load,pv), origin, horizon_step, member'}}
    (output_dir/'f1_test_results.json').write_text(canonical_json(test_data))
    verify_inputs()
    if any(digest(ARTIFACTS/name)!=value for name,value in protected.items()):
        raise ValueError('Protected artifact changed during benchmark')
    if digest(output_dir/'f1_champions.json') != freeze_hash:
        raise ValueError('Champion configuration changed after test unlock')
    names = ('f1_leaderboard.json','f1_champions.json','f1_test_results.json','f1_test_predictions.csv')
    hashes = {name:digest(output_dir/name) for name in names}
    if verify_against and any(digest(Path(verify_against)/name)!=value for name,value in hashes.items()):
        raise ValueError('Reproduction differs; predictions have not been normalised')
    families = {}
    for rt in runtimes.values():
        families[rt['family']] = families.get(rt['family'],0.) + rt['training_seconds']+rt['prediction_seconds']
    slowest = max(runtimes,key=lambda k:runtimes[k]['training_seconds']+runtimes[k]['prediction_seconds'])
    (output_dir/'f1.runtime.json').write_text(canonical_json({'total_seconds':perf_counter()-started,
        'measurements':runtimes,'family_seconds':families,'slowest_candidate':slowest,
        'artifact_hashes':hashes,'reproduction_byte_identical':True if verify_against else None}))
    print(canonical_json({'champions':{t:champions[t]['configuration']['model_id'] for t in TARGETS},
                          'artifact_hashes':hashes,'total_seconds':perf_counter()-started}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--verify-against', type=Path, help='Reproduce a completed run without test-guided changes')
    args = parser.parse_args()
    run_f1(args.output_dir, args.verify_against)
