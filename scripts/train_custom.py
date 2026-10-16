"""Standalone training/testing with configurable contiguous synthetic-date splits."""
import argparse
import json
from pathlib import Path

from comfair.forecasting.configurable_engine import (
    DEFAULT_SPLITS, parse_and_validate_splits, execute_training_and_evaluation,
)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--splits-json", type=Path, help="JSON: train/validation/test start_date/end_date")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/custom"))
    args = parser.parse_args()
    raw = json.loads(args.splits_json.read_text()) if args.splits_json else DEFAULT_SPLITS
    validated = parse_and_validate_splits(raw)
    result = execute_training_and_evaluation(validated)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / "evaluation.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"output": str(target), "models": result["model_configs"],
                      "validation_metrics": result["validation_metrics"],
                      "test_metrics": result["test_metrics"]}, indent=2))

if __name__ == "__main__":
    main()
