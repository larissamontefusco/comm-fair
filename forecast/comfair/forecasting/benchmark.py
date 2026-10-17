"""Reproduce F0: python -m comfair.forecasting.benchmark --output-dir PATH."""
import argparse
import csv
from hashlib import sha256
import platform
from pathlib import Path
from time import perf_counter

import numpy as np
import openpyxl
import yaml

from .baselines import MODELS, forecast
from .data import load_forecasting_data, resolve_source_record
from .metrics import EPSILON_KW, aggregate_metrics
from .schemas import MEMBERS, TARGETS, canonical_json
from .splits import SPLITS, split_metadata


def run_f0(output_dir):
    started = perf_counter()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Standalone edition: no optimiser-generated M3/M4 artifact dependency.
    protected = []
    protected_hashes = {}
    dataset, audit = load_forecasting_data()
    code_hash = sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        code_hash.update(path.name.encode() + b'\0' + path.read_bytes())
    provenance = {'sources': audit['sources'], 'forecasting_source_sha256': code_hash.hexdigest(),
                  'python': platform.python_version(), 'numpy': np.__version__,
                  'openpyxl': openpyxl.__version__, 'pyyaml': yaml.__version__,
                  'protected_artifact_hashes': protected_hashes}
    audit['provenance'] = provenance
    prediction_path = output_dir / 'f0_predictions.csv'
    evaluations = {}
    runtime_models = {}
    row_count = 0
    with prediction_path.open('w', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['split','model_id','target','origin_t','target_t','horizon_step','member_id','y_pred','y_true','error','absolute_error'])
        for split in SPLITS[1:]:
            evaluations[split.name] = {}
            for model in MODELS:
                evaluations[split.name][model] = {}
                for target in TARGETS:
                    timer = perf_counter()
                    actual, predicted = [], []
                    diagnostics = dict(clipping_count=0, clipping_magnitude_kw_sum=0., fallback_count=0,
                                       cold_start_zero_count=0, deterministic_zero_pv_count=0)
                    for o in split.origins:
                        # Only this prefix reaches forecast(); future actuals are
                        # retrieved separately AFTER predictions have been issued.
                        result = forecast(dataset.history(target,o), target=target, model_id=model,
                                          zero_pv_members=dataset.zero_pv_members)
                        pred = np.asarray([p.y_pred for p in result.predictions]).reshape(24,9)
                        truth = getattr(dataset,target)[o:o+24]
                        actual.append(truth)
                        predicted.append(pred)
                        for key in diagnostics: diagnostics[key] += result.diagnostics[key]
                        for r in result.predictions:
                            truth_value = float(truth[r.horizon_step-1,r.member_id-1])
                            error = r.y_pred - truth_value
                            writer.writerow([split.name,model,target,o,r.target_t,r.horizon_step,r.member_id,
                                             repr(r.y_pred),repr(truth_value),repr(error),repr(abs(error))])
                            row_count += 1
                    eligible = MEMBERS if target=='load_kw' else tuple(i for i in MEMBERS if i not in dataset.zero_pv_members)
                    evaluations[split.name][model][target] = {
                        'metrics': aggregate_metrics(actual,predicted,percentage_members=eligible),
                        'diagnostics': diagnostics, 'origin_count': len(split.origins),
                        'first_origin': split.start, 'last_origin': split.stop-24}
                    runtime_models[f'{split.name}/{model}/{target}'] = perf_counter()-timer
    audit_path = output_dir/'f0_data_audit.json'
    audit_path.write_text(canonical_json(audit))
    summary = {'schema_version':1,'milestone':'F0','status':'PASS','provenance':provenance,
               'configuration': {'random_seed':0,'horizon_hours':24,'origin_cadence_hours':24,
                                 'horizon_step':'public 1..24; target_t=origin_t+horizon_step-1',
                                 'as_of':'last observed ordinal = origin_t-1; history t<origin',
                                 'split':split_metadata(),'model_ids':list(MODELS),
                                 'baselines':{'persistence':'y[o-1] at every horizon',
                                              'naive_24':'y[target_t-24]', 'naive_168':'y[target_t-168]'},
                                 'fallback':'missing seasonal lag -> persistence; empty history -> zero',
                                 'zero_pv_members':list(dataset.zero_pv_members),
                                 'clipping':'negative prediction -> zero; count and sum magnitudes recorded',
                                 'refit':'none; no fitting, transforms or model selection',
                                 'metric_policy':{'percentage_units':'ratio; multiply by 100 for percent',
                                                  'epsilon_kw':EPSILON_KW,'wape':'null if sum(abs(y)) <= n*epsilon',
                                                  'smape':'mean(2*abs(error)/(abs(y)+abs(pred))); exclude pairs <= epsilon; null if none',
                                                  'pv_percentages':'PV owners only; zero-capacity members retained in native metrics'},
                                 'row_order':'split(validation,test), model(persistence,naive_24,naive_168), target(load,pv), origin, horizon_step, member'},
               'validation':evaluations['validation'], 'test_descriptive_only':evaluations['test'],
               'test_use':'Descriptive fixed baseline reference only; no selection or tuning, no F1 champion.',
               'data_audit_sha256':sha256(audit_path.read_bytes()).hexdigest(),
               'predictions':{'file':prediction_path.name,'sha256':sha256(prediction_path.read_bytes()).hexdigest(),'rows':row_count}}
    summary_path = output_dir/'f0_baselines.json'
    summary_path.write_text(canonical_json(summary))
    for path in protected:
        if sha256(path.read_bytes()).hexdigest()!=protected_hashes[path.name]:
            raise ValueError('Protected M3/M4 artifact changed')
    for source in audit['sources'].values():
        path = resolve_source_record(source)
        if sha256(path.read_bytes()).hexdigest()!=source['sha256']:
            raise ValueError('Source changed during F0 run')
    hashes = {p.name:sha256(p.read_bytes()).hexdigest() for p in (audit_path,summary_path,prediction_path)}
    (output_dir/'f0.runtime.json').write_text(canonical_json({'total_seconds':perf_counter()-started,
        'evaluation_seconds':runtime_models,'artifact_hashes':hashes}))
    print(canonical_json({'artifact_hashes':hashes,'prediction_rows':row_count,'total_seconds':perf_counter()-started}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True,type=Path)
    run_f0(parser.parse_args().output_dir)
