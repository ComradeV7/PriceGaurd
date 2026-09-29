"""Validation check protocol and Finding model."""

from dataclasses import dataclass, field
from typing import Any, Protocol

import pandas as pd

from priceguard.config import Config

SEVERITY_ORDER = {"PASS": 0, "WARN": 1, "BREACH": 2, "CRITICAL": 3}


@dataclass
class Finding:
    """A single exception raised by a check."""

    position_id: str
    mark_date: pd.Timestamp
    check_name: str
    severity: str
    mark: float | None = None
    reference_price: float | None = None
    deviation_bps: float | None = None
    mv_impact_usd: float | None = None
    suspected_cause: str | None = None
    is_material: bool = False
    facts: dict[str, Any] = field(default_factory=dict)


class Check(Protocol):
    """Protocol for a validation check.

    A check receives the validation context (marks joined with
    positions, instruments and reference prices) plus the loaded
    configuration, and returns findings. Checks must never read the
    ground_truth table.
    """

    name: str

    def run(self, context: pd.DataFrame, config: Config) -> list[Finding]:
        """Execute the check against the context panel."""
        ...


def tolerance_for(asset_class: str, fv_level: int, config: Config) -> Any:
    """Return the tolerance entry for an instrument class/level."""
    t = config.tolerances
    if fv_level == 3:
        return t.l3
    mapping = {
        ("equity", 1): t.equity_l1,
        ("bond_etf", 1): t.bond_etf_l1,
        ("fx", 1): t.fx_l1,
        ("bond_l2", 2): t.bond_l2,
    }
    entry = mapping.get((asset_class, fv_level))
    if entry is None:
        raise ValueError(
            f"No tolerance configured for asset_class={asset_class}, "
            f"fv_level={fv_level}"
        )
    return entry
