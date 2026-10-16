"""
Typed data models for ComFair benchmark.

These models represent pure data structures extracted from the official
ComErgy 2026 benchmark workbook. They are kept separate from modelling
assumptions and Pyomo components.
"""

from dataclasses import dataclass
from typing import Dict
import numpy as np
from datetime import datetime
from pathlib import Path


@dataclass
class DGSInstallation:
    """Distributed Generation System (PV/BESS) installation for a member."""

    member_id: int  # 1-9
    pv_modules: int = 0
    battery_modules: int = 0

    def has_any_asset(self) -> bool:
        """Check if member has any DGS assets."""
        return self.pv_modules > 0 or self.battery_modules > 0

    def __repr__(self) -> str:
        """Human-readable representation."""
        parts = []
        if self.pv_modules > 0:
            parts.append(f"{self.pv_modules} PV")
        if self.battery_modules > 0:
            parts.append(f"{self.battery_modules} battery")
        if not parts:
            return f"Member {self.member_id}: No assets"
        return f"Member {self.member_id}: {', '.join(parts)}"


@dataclass
class MemberData:
    """Demographic and asset data for one community member."""

    member_id: int  # 1-9
    household_type: str
    occupant_count: int
    annual_income_aud: float  # After-tax annual income in AUD
    dgs: DGSInstallation

    def __repr__(self) -> str:
        """Human-readable member summary."""
        return (
            f"Member {self.member_id}: {self.occupant_count} occupants, "
            f"${self.annual_income_aud:,.0f} income, {self.dgs}"
        )


@dataclass
class BenchmarkData:
    """
    Complete ComErgy 2026 benchmark dataset.

    Contains 8760 hourly periods for 9 members, tariffs, weather, and metadata.
    All data is extracted directly from the official workbook without embedded
    modelling assumptions.
    """

    # Identification and provenance
    workbook_path: str
    workbook_sheet: str
    load_timestamp: datetime

    # Hourly demand data [period, member_id-1] → kW or kWh
    demand_hourly: np.ndarray  # Shape: (8760, 9)

    # Hourly tariff/environmental data
    grid_import_tariff_raw: np.ndarray  # Shape: (8760,) raw workbook values; scale unresolved
    feedin_tariff_raw: np.ndarray      # Shape: (8760,) raw workbook values; scale unresolved
    temperature_c: np.ndarray                 # Shape: (8760,) in °C
    ghi_w_per_m2: np.ndarray                 # Shape: (8760,) in W/m²

    # Scalar metadata
    location: str
    price_unit: str  # e.g., "AUD"
    daily_connection_fee: float  # e.g., 1.0 AUD
    daily_connection_fee_unit: str  # e.g., "AUD"

    # Member-specific metadata
    members: Dict[int, MemberData]  # Key: member_id (1-9), Value: MemberData

    source_notes: Dict[str, str]
    workbook_sha256: str
    tariff_unit_status: str = "unresolved: c/kWh headers versus Australian Dollar note; raw values unchanged"
    period_order: str = "row 3 + t for t=0..8759; hourly Jan 1-Dec 31; year/timezone/DST unspecified"

    # Dimensions
    member_count: int = 9
    period_count: int = 8760

    # Source verification
    expected_workbook_path: str = "backend/reader/ComErgy Benchmark Dataset 2026.xlsx"
    expected_sheet: str = "ComErgy Benchmark Dataset 2026"

    def validate(self) -> None:
        """
        Validate data invariants. Raises ValueError if constraints violated.

        Checks:
        - Exactly 9 members
        - Exactly 8760 hourly periods
        - All hourly arrays have correct shape
        - Member IDs are 1-9
        - No missing values in required fields
        - Demand and GHI are non-negative
        - Tariff values are positive
        """
        # Count invariants
        if self.member_count != 9:
            raise ValueError(f"Expected 9 members, got {self.member_count}")
        if self.period_count != 8760:
            raise ValueError(f"Expected 8760 periods, got {self.period_count}")

        # Array shape checks
        if self.demand_hourly.shape != (8760, 9):
            raise ValueError(
                f"demand_hourly shape {self.demand_hourly.shape}, expected (8760, 9)"
            )
        if self.grid_import_tariff_raw.shape != (8760,):
            raise ValueError(
                f"grid_import_tariff shape {self.grid_import_tariff_raw.shape}, "
                "expected (8760,)"
            )
        if self.feedin_tariff_raw.shape != (8760,):
            raise ValueError(
                f"feedin_tariff shape {self.feedin_tariff_raw.shape}, "
                "expected (8760,)"
            )
        if self.temperature_c.shape != (8760,):
            raise ValueError(
                f"temperature_c shape {self.temperature_c.shape}, expected (8760,)"
            )
        if self.ghi_w_per_m2.shape != (8760,):
            raise ValueError(
                f"ghi_w_per_m2 shape {self.ghi_w_per_m2.shape}, expected (8760,)"
            )

        # Members check
        if len(self.members) != 9:
            raise ValueError(f"Expected 9 member records, got {len(self.members)}")
        member_ids = set(self.members.keys())
        if member_ids != set(range(1, 10)):
            raise ValueError(f"Expected member IDs 1-9, got {member_ids}")

        # Missing values check
        if not np.isfinite(self.demand_hourly).all():
            raise ValueError("Non-finite values in demand_hourly")
        if not np.isfinite(self.grid_import_tariff_raw).all():
            raise ValueError("Non-finite values in grid_import_tariff")
        if not np.isfinite(self.feedin_tariff_raw).all():
            raise ValueError("Non-finite values in feedin_tariff")
        if not np.isfinite(self.temperature_c).all():
            raise ValueError("Non-finite values in temperature_c")
        if not np.isfinite(self.ghi_w_per_m2).all():
            raise ValueError("Non-finite values in ghi_w_per_m2")

        # Non-negativity checks
        if (self.demand_hourly < 0).any():
            raise ValueError("Negative values in demand_hourly")
        if (self.ghi_w_per_m2 < 0).any():
            raise ValueError("Negative values in ghi_w_per_m2")
        if (self.grid_import_tariff_raw <= 0).any():
            raise ValueError("Non-positive tariff values in grid_import_tariff")
        if (self.feedin_tariff_raw <= 0).any():
            raise ValueError("Non-positive values in feedin_tariff")

        if (self.feedin_tariff_raw > self.grid_import_tariff_raw).any():
            raise ValueError("Feed-in tariff exceeds grid import tariff")
        if not self.location.strip() or self.price_unit != "AUD":
            raise ValueError("Incomplete scalar metadata")
        if not np.isfinite(self.daily_connection_fee) or self.daily_connection_fee < 0:
            raise ValueError("Invalid daily connection fee")
        if self.daily_connection_fee_unit != self.price_unit:
            raise ValueError("Connection fee currency mismatch")
        for mid, member in self.members.items():
            if member.member_id != mid or member.dgs.member_id != mid:
                raise ValueError("Member identity mismatch")
            if not member.household_type.strip():
                raise ValueError("Missing household type")
            if type(member.occupant_count) is not int or member.occupant_count <= 0:
                raise ValueError("Invalid occupant count")
            if not np.isfinite(member.annual_income_aud) or member.annual_income_aud <= 0:
                raise ValueError("Invalid annual income")
            for count in (member.dgs.pv_modules, member.dgs.battery_modules):
                if type(count) is not int or count < 0:
                    raise ValueError("Invalid module count")

    def summary(self) -> Dict:
        """
        Generate a summary dictionary with key benchmark statistics.

        Returns:
            Dictionary containing member count, period count, annual demand
            per member and aggregate, peak demand, PV/BESS ownership info,
            tariff ranges, and metadata.
        """
        self.validate()
        annual_demand_per_member = self.demand_hourly.sum(axis=0)  # Sum over hours
        total_annual_demand = annual_demand_per_member.sum()
        aggregate_peak_demand = self.demand_hourly.sum(axis=1).max()

        pv_owners = [mid for mid, m in self.members.items() if m.dgs.pv_modules > 0]
        pv_module_count = sum(m.dgs.pv_modules for m in self.members.values())

        bess_owners = [mid for mid, m in self.members.items() if m.dgs.battery_modules > 0]
        bess_module_count = sum(m.dgs.battery_modules for m in self.members.values())

        return {
            "metadata": {
                "location": self.location,
                "price_unit": self.price_unit,
                "daily_connection_fee": self.daily_connection_fee,
                "daily_connection_fee_unit": self.daily_connection_fee_unit,
                "workbook": Path(self.workbook_path).name,
                "workbook_sha256": self.workbook_sha256,
                "source_notes": self.source_notes,
                "tariff_unit_status": self.tariff_unit_status,
                "period_order": self.period_order,
                "capacity_conversion": "none; module counts only",
                "sheet": self.workbook_sheet,
            },
            "dimensions": {
                "member_count": self.member_count,
                "period_count": self.period_count,
            },
            "demand": {
                "annual_sum_raw": float(total_annual_demand),
                "unit_note": self.source_notes["A1"],
                "annual_demand_per_member": {
                    i: float(annual_demand_per_member[i-1])
                    for i in range(1, 10)
                },
                "aggregate_peak_raw": float(aggregate_peak_demand),
                "average_hourly_raw": float(total_annual_demand / 8760),
            },
            "pv": {
                "owners": pv_owners,
                "total_modules": int(pv_module_count),
                "module_distribution": {
                    m_id: self.members[m_id].dgs.pv_modules
                    for m_id in pv_owners
                },
            },
            "bess": {
                "owners": bess_owners,
                "total_modules": int(bess_module_count),
                "module_distribution": {
                    m_id: self.members[m_id].dgs.battery_modules
                    for m_id in bess_owners
                },
            },
            "tariffs": {
                "grid_import_raw": {
                    "min": float(self.grid_import_tariff_raw.min()),
                    "max": float(self.grid_import_tariff_raw.max()),
                    "mean": float(self.grid_import_tariff_raw.mean()),
                    "constant": bool(
                        (self.grid_import_tariff_raw ==
                         self.grid_import_tariff_raw[0]).all()
                    ),
                    "unique_values": sorted(
                        float(x) for x in
                        np.unique(self.grid_import_tariff_raw)
                    ),
                },
                "feedin_raw": {
                    "min": float(self.feedin_tariff_raw.min()),
                    "max": float(self.feedin_tariff_raw.max()),
                    "mean": float(self.feedin_tariff_raw.mean()),
                    "constant": bool(
                        (self.feedin_tariff_raw ==
                         self.feedin_tariff_raw[0]).all()
                    ),
                    "unique_values": sorted(
                        float(x) for x in
                        np.unique(self.feedin_tariff_raw)
                    ),
                },
            },
            "weather": {
                "temperature_c": {
                    "min": float(self.temperature_c.min()),
                    "max": float(self.temperature_c.max()),
                    "mean": float(self.temperature_c.mean()),
                },
                "ghi_w_per_m2": {
                    "min": float(self.ghi_w_per_m2.min()),
                    "max": float(self.ghi_w_per_m2.max()),
                    "mean": float(self.ghi_w_per_m2.mean()),
                },
            },
            "members": {
                m_id: {
                    "household_type": member.household_type,
                    "occupant_count": member.occupant_count,
                    "annual_income_aud": member.annual_income_aud,
                    "pv_modules": member.dgs.pv_modules,
                    "battery_modules": member.dgs.battery_modules,
                }
                for m_id, member in self.members.items()
            },
        }
