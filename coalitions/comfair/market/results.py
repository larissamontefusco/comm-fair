"""Serializable market domain types; no Pyomo objects escape the pricing pass."""
from dataclasses import asdict, dataclass
from hashlib import sha256

from comfair.physical.config import canonical_json

# Engineering tolerance for price classification, not an economic price adjustment.
PRICE_TOLERANCE_AUD_PER_KWH = 1e-8


def physical_fingerprint(physical) -> str:
    return sha256(physical.to_json(include_runtime=False).encode()).hexdigest()


@dataclass
class MemberPositions:
    residual_kw: list[float]
    deficit_kw: list[float]
    surplus_kw: list[float]
    local_buy_kw: list[float]
    local_sell_kw: list[float]
    net_local_position_kw: list[float]
    grid_import_kw: list[float]
    grid_export_kw: list[float]


@dataclass
class MatchingResult:
    members: dict[int, MemberPositions]
    aggregate_deficit_kw: list[float]
    aggregate_surplus_kw: list[float]
    local_trade_kw: list[float]
    diagnostics: dict[str, float]


@dataclass
class PricingResult:
    raw_dual_aud_per_kw: list[float]
    lambda_aud_per_kwh: list[float]
    protected_price_aud_per_kwh: list[float]
    clipped: list[bool]
    clipping_direction: list[str]
    objective_aud: float
    objective_residual_aud: float
    physical_result_sha256: str
    solver: dict


@dataclass
class MemberSettlement:
    B_i_aud: float
    fixed_fee_aud: float
    grid_import_kwh: float
    grid_export_kwh: float
    local_buy_kwh: float
    local_sell_kwh: float
    grid_import_charge_aud: float
    grid_export_revenue_aud: float
    local_purchase_charge_aud: float
    local_sale_revenue_aud: float
    C_market_aud: float
    u0_aud: float
    harmed: bool


@dataclass
class MarketResult:
    members: dict[int, MemberSettlement]
    member_hourly: dict[int, MemberPositions]
    hourly: dict[str, list]
    kpis: dict
    diagnostics: dict
    pricing: dict
    provenance: dict
    schema_version: int = 1

    def to_dict(self, *, include_runtime: bool = True) -> dict:
        result = asdict(self)
        for field in ('members', 'member_hourly'):
            result[field] = {str(i): result[field][i] for i in sorted(result[field])}
        if not include_runtime:
            result['pricing'].pop('runtime_seconds', None)
        return result

    def to_json(self, *, include_runtime: bool = True) -> str:
        return canonical_json(self.to_dict(include_runtime=include_runtime))
