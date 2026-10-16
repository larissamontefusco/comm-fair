"""Pure validation and projection helpers for persisted forecast runs."""

from hashlib import sha256
import json
import math


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def payload_sha256(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_member_ids(member_ids, allowed_member_ids) -> list[int]:
    allowed = tuple(int(member_id) for member_id in allowed_member_ids)
    requested = allowed if member_ids is None else tuple(member_ids)
    if not requested:
        raise ValueError("At least one member must be selected")
    if any(type(member_id) is not int for member_id in requested):
        raise ValueError("member_ids must contain integers")
    if len(set(requested)) != len(requested):
        raise ValueError("member_ids cannot contain duplicates")
    unknown = sorted(set(requested) - set(allowed))
    if unknown:
        raise ValueError(f"Members are not available in this community: {unknown}")
    requested_set = set(requested)
    return [member_id for member_id in allowed if member_id in requested_set]


def member_set_key(member_ids) -> str:
    return ",".join(str(member_id) for member_id in sorted(member_ids))


def decode_member_ids(raw) -> list[int]:
    values = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(values, list) or not values or any(type(value) is not int for value in values):
        raise ValueError("Persisted member_ids are invalid")
    if len(values) != len(set(values)):
        raise ValueError("Persisted member_ids contain duplicates")
    return values


def validate_forecast_results(results: dict, *, origin_t: int, member_ids: list[int], horizon_hours: int) -> None:
    if not isinstance(results, dict):
        raise ValueError("Forecast results must be an object")
    if results.get("origin_t") != origin_t or results.get("horizon_hours") != horizon_hours:
        raise ValueError("Forecast result window does not match the run")
    if results.get("member_ids") != member_ids or results.get("column_order") != member_ids:
        raise ValueError("Forecast result member mapping does not match the run")

    timestamps = results.get("timestamps")
    if not isinstance(timestamps, list) or len(timestamps) != horizon_hours:
        raise ValueError("Forecast timestamps do not cover the complete horizon")
    if len(set(timestamps)) != horizon_hours:
        raise ValueError("Forecast timestamps contain duplicates")

    expected_width = len(member_ids)
    for field in ("load_kw", "pv_available_kw"):
        matrix = results.get(field)
        if not isinstance(matrix, list) or len(matrix) != horizon_hours:
            raise ValueError(f"{field} does not cover the complete horizon")
        for row in matrix:
            if not isinstance(row, list) or len(row) != expected_width:
                raise ValueError(f"{field} has an invalid member dimension")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in row
            ):
                raise ValueError(f"{field} contains non-finite or non-numeric values")

    units = results.get("units")
    if units != {"load_kw": "kW", "pv_available_kw": "kW"}:
        raise ValueError("Forecast units are missing or invalid")


def project_forecast_results(results: dict, requested_member_ids: list[int]) -> dict:
    """Project one persisted run to a compatible subset without combining runs."""
    stored_member_ids = results["member_ids"]
    positions = {member_id: index for index, member_id in enumerate(stored_member_ids)}
    if any(member_id not in positions for member_id in requested_member_ids):
        raise ValueError("Persisted run does not cover all requested members")

    projected = {
        key: value
        for key, value in results.items()
        if key not in {"member_ids", "column_order", "load_kw", "pv_available_kw"}
    }
    projected["member_ids"] = list(requested_member_ids)
    projected["column_order"] = list(requested_member_ids)
    projected["load_kw"] = [
        [row[positions[member_id]] for member_id in requested_member_ids]
        for row in results["load_kw"]
    ]
    projected["pv_available_kw"] = [
        [row[positions[member_id]] for member_id in requested_member_ids]
        for row in results["pv_available_kw"]
    ]
    return projected
