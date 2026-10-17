"""Standard-library JSON helpers shared by the standalone game package."""

import json


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
