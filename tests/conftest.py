"""Shared test fixtures (offline, no network)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from priceguard.config import (
    Config,
    CrossSourceConfig,
    DriftConfig,
    FaultInjectionConfig,
    FaultParameters,
    InstrumentConfig,
    MarkNoiseConfig,
    MaterialityConfig,
    PathsConfig,
    PortfolioConfig,
    QuantityRange,
    ReturnOutlierConfig,
    SettingsConfig,
    SeverityConfig,
    StaleConfig,
    TolerancesConfig,
    ToleranceThreshold,
    UniverseConfig,
    YieldCurveConfig,
)

CONFIG_DIR = Path(__file__).parent.parent / "config"


@pytest.fixture
def real_config() -> Config:
    """Load the committed configuration files."""
    return Config.load(CONFIG_DIR)


def make_config(seed: int = 42) -> Config:
    """Build a minimal in-memory config for unit tests."""
    settings = SettingsConfig(
        seed=seed,
        base_currency="USD",
        lookback_business_days=20,
        paths=PathsConfig(
            data_raw=Path("data/raw"),
            data_sample=Path("data/sample"),
            exports=Path("exports"),
            db=Path(":memory:"),
        ),
        portfolio=PortfolioConfig(
            books=["Trading-A", "Treasury", "Banking-B"],
            quantity_ranges={
                "equity": QuantityRange(min=1000, max=100000),
                "bond_etf": QuantityRange(min=1000, max=100000),
                "fx": QuantityRange(min=100000, max=10000000),
                "bond_l2": QuantityRange(min=100, max=10000),
                "l3": QuantityRange(min=1, max=100),
            },
        ),
        mark_noise=MarkNoiseConfig(
            equity=0.0005,
            bond_etf=0.0005,
            fx=0.0002,
            bond_l2=0.0008,
            l3_daily_walk=0.001,
        ),
        yield_curve=YieldCurveConfig(
            tenors_years=[2, 5, 10, 30],
            fred_series=["DGS2", "DGS5", "DGS10", "DGS30"],
        ),
    )

    instruments = [
        InstrumentConfig(
            ticker="EQ1",
            name="Test Equity",
            asset_class="equity",
            currency="USD",
            fv_level=1,
            ref_source="yahoo",
        ),
        InstrumentConfig(
            ticker="FX1",
            name="Test FX",
            asset_class="fx",
            currency="USD",
            fv_level=1,
            ref_source="fx",
        ),
        InstrumentConfig(
            ticker="BD2",
            name="Test L2 Bond",
            asset_class="bond_l2",
            currency="USD",
            fv_level=2,
            ref_source="fred",
            coupon=0.04,
            maturity_years=10,
        ),
        InstrumentConfig(
            ticker="L3A",
            name="Test L3",
            asset_class="l3",
            currency="USD",
            fv_level=3,
            ref_source="none",
            model_value=1_000_000.0,
            model_band_pct=5.0,
        ),
    ]
    universe = UniverseConfig(instruments=instruments)

    tolerances = TolerancesConfig(
        equity_l1=ToleranceThreshold(warn_bps=50, breach_bps=100),
        bond_etf_l1=ToleranceThreshold(warn_bps=75, breach_bps=150),
        fx_l1=ToleranceThreshold(warn_bps=25, breach_bps=50),
        bond_l2=ToleranceThreshold(warn_bps=30, breach_bps=75),
        l3=ToleranceThreshold(band_pct=5.0, daily_move_pct=2.0),
        severity=SeverityConfig(critical_multiple=5),
        stale=StaleConfig(min_days=2, ref_move_bps=20),
        drift=DriftConfig(consecutive_days=3),
        return_outlier=ReturnOutlierConfig(
            mad_multiple=5.0, window_days=10, min_mad_bps=10.0
        ),
        cross_source=CrossSourceConfig(max_diff_bps=50),
        materiality=MaterialityConfig(mv_threshold_usd=10000),
    )

    fault_injection = FaultInjectionConfig(
        injection_rate=0.04,
        subtle_fraction=0.10,
        fault_type_weights={
            "STALE": 0.25,
            "FAT_FINGER": 0.25,
            "MISSING": 0.20,
            "DRIFT": 0.20,
            "CURRENCY_MISMATCH": 0.10,
        },
        fault_parameters={
            "STALE": FaultParameters(min_consecutive_days=2, max_consecutive_days=5),
            "FAT_FINGER": FaultParameters(
                multipliers=[10.0, 0.1, 0.01], transposition_probability=0.3
            ),
            "MISSING": FaultParameters(probability=1.0),
            "DRIFT": FaultParameters(
                min_days=10,
                max_days=20,
                bps_per_day_min=5,
                bps_per_day_max=15,
                target_levels=[2, 3],
            ),
            "CURRENCY_MISMATCH": FaultParameters(target_currencies=["INR", "USD"]),
        },
    )

    return Config(
        settings=settings,
        universe=universe,
        tolerances=tolerances,
        fault_injection=fault_injection,
    )


@pytest.fixture
def mini_config() -> Config:
    """Minimal in-memory config."""
    return make_config()


def make_panel(
    marks: list[float | None],
    refs: list[float | None],
    asset_class: str = "equity",
    fv_level: int = 1,
    quantity: float = 1000.0,
    position_currency: str = "USD",
    start: str = "2024-01-01",
    position_id: str = "POS-1",
    instrument_id: str = "EQ1",
    extra_columns: dict | None = None,
) -> pd.DataFrame:
    """Build a hand-made validation context panel."""
    dates = pd.bdate_range(start=start, periods=len(marks))
    data = {
        "position_id": position_id,
        "mark_date": dates,
        "mark": marks,
        "mark_currency": position_currency,
        "instrument_id": instrument_id,
        "book": "Trading-A",
        "quantity": quantity,
        "position_currency": position_currency,
        "ticker": instrument_id,
        "name": instrument_id,
        "asset_class": asset_class,
        "fv_level": fv_level,
        "ref_source": "yahoo",
        "reference_price": refs,
        "reference_source": "yahoo",
    }
    if extra_columns:
        data.update(extra_columns)
    return pd.DataFrame(data)


def random_walk(n: int, start_price: float, seed: int) -> np.ndarray:
    """Seeded random walk of prices."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 0.01, size=n)
    return start_price * np.exp(np.cumsum(steps))
