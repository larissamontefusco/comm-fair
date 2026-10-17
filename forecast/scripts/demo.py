"""Standalone 24-hour inference, optionally measured against held-out truth."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np

from comfair.forecasting.baselines import forecast as baseline
from comfair.forecasting.data import load_forecasting_csv_data, load_forecasting_data
from comfair.forecasting.models import Candidate, fit_candidate
from comfair.forecasting.metrics import aggregate_metrics
from comfair.forecasting.schemas import MEMBERS, canonical_json


def run(origin_t=7008, output_dir=Path("outputs/demo"), model="champion",
        load_csv=None, pv_csv=None):
    if not (isinstance(origin_t, int) and origin_t % 24 == 0 and 7008 <= origin_t <= 8736):
        raise ValueError("Use a test-set daily origin_t: 7008, 7032, ... 8736")
    if (load_csv is None) != (pv_csv is None):
        raise ValueError("Provide both load_csv and pv_csv, or neither")
    dataset, audit = (load_forecasting_csv_data(load_csv, pv_csv)
                      if load_csv is not None else load_forecasting_data())
    if model not in ("champion", "naive_24"):
        raise ValueError("model must be champion or naive_24")
    fitted = None
    if model == "champion":
        # Reference F1: refit load Ridge on train + validation, then hold fixed.
        candidate = Candidate("ridge", "global", {"alpha": 0.1, "solver": "svd"})
        fitted = fit_candidate(candidate, dataset.history("load_kw", 7008),
                               "load_kw", dataset.zero_pv_members)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    scores = {}
    with (output_dir / "predictions.csv").open("w", newline="") as fp:
        writer = csv.writer(fp, lineterminator="\n")
        writer.writerow(["origin_t", "target_t", "horizon_step", "member_id",
                         "target", "model_id", "predicted_kw", "actual_kw"])
        for target in ("load_kw", "pv_available_kw"):
            history = dataset.history(target, origin_t)
            result = (fitted.forecast(history, provenance=dataset.provenance)
                      if target == "load_kw" and fitted is not None else
                      baseline(history, target=target, model_id="naive_24",
                               zero_pv_members=dataset.zero_pv_members,
                               provenance=dataset.provenance))
            true = getattr(dataset, target)[origin_t:origin_t + 24]
            pred = np.array([p.y_pred for p in result.predictions]).reshape(24, 9)
            for p in result.predictions:
                writer.writerow((p.origin_t, p.target_t, p.horizon_step, p.member_id,
                                 target, result.model_id, repr(p.y_pred),
                                 repr(float(true[p.horizon_step - 1, p.member_id - 1]))))
            eligible = MEMBERS if target == "load_kw" else tuple(
                i for i in MEMBERS if i not in dataset.zero_pv_members)
            scores[target] = {"model_id": result.model_id,
                              "micro": aggregate_metrics([true], [pred],
                                  percentage_members=eligible)["micro"]}
    summary = {"kind": "historical_holdout_demonstration", "origin_t": origin_t,
               "horizon_hours": 24, "units": "kW", "metrics": scores,
               "data_source": audit.get("source_kind", "canonical_benchmark"),
               "source_sha256": {k: v["sha256"] for k, v in audit["sources"].items()
                                  if k in ("load_csv", "pv_csv")},
               "note": "Actuals are joined after prediction for retrospective evaluation only. "
                       "Synthetic dataset hours are not live timestamps."}
    (output_dir / "summary.json").write_text(canonical_json(summary))
    print(json.dumps({"csv": str(output_dir / "predictions.csv"),
                      "summary": str(output_dir / "summary.json"),
                      "models": {k: v["model_id"] for k, v in scores.items()}},
                     indent=2))
    return summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin-t", type=int, default=7008)
    parser.add_argument("--model", choices=("champion", "naive_24"), default="champion")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/demo"))
    parser.add_argument("--load-csv", type=Path,
                        help="Standalone consumption CSV (requires --pv-csv)")
    parser.add_argument("--pv-csv", type=Path,
                        help="Standalone production CSV (requires --load-csv)")
    args = parser.parse_args()
    run(args.origin_t, args.output_dir, args.model, args.load_csv, args.pv_csv)
