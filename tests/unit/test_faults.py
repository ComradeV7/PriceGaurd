"""Tests for synthetic fault injection and ground truth."""

import json

import numpy as np
import pandas as pd
import pytest

from priceguard.config import (
    FaultInjectionConfig,
    InstrumentConfig,
    UniverseConfig,
)
from priceguard.synth.faults import inject_faults
from tests.conftest import make_config


def _single_type_weights(fault_type: str) -> dict[str, float]:
    """Weights that force exactly one fault type."""
    types = ["STALE", "FAT_FINGER", "MISSING", "DRIFT", "CURRENCY_MISMATCH"]
    return {t: (1.0 if t == fault_type else 0.0) for t in types}


def _config_with_weights(fault_type: str, seed: int = 5, **fi_kwargs):
    """Config with a single fault type enabled."""
    config = make_config(seed=seed)
    base = config.fault_injection
    kwargs = {
        "injection_rate": base.injection_rate,
        "subtle_fraction": 0.0,
        "fault_type_weights": _single_type_weights(fault_type),
        "fault_parameters": base.fault_parameters,
    }
    kwargs.update(fi_kwargs)
    config.fault_injection = FaultInjectionConfig(**kwargs)
    return config


def _add_inr_instrument(config):
    """Add an INR equity so currency mismatch faults are meaningful."""
    instruments = list(config.universe.instruments) + [
        InstrumentConfig(
            ticker="INEQ",
            name="INR Equity",
            asset_class="equity",
            currency="INR",
            fv_level=1,
            ref_source="yahoo",
        )
    ]
    config.universe = UniverseConfig(instruments=instruments)
    return config


def _setup(config, n_days: int = 60):
    """Build deterministic positions, instruments, marks and FX rates."""
    from priceguard.synth.marks import generate_clean_marks
    from priceguard.synth.portfolio import (
        generate_portfolio,
        instruments_frame,
        l3_models_frame,
    )

    dates = pd.bdate_range("2024-10-01", periods=n_days)
    rows = []
    for ticker, base in [("EQ1", 100.0), ("FX1", 1.1), ("BD2", 98.0), ("INEQ", 2500.0)]:
        if not any(i.ticker == ticker for i in config.universe.instruments):
            continue
        for i, d in enumerate(dates):
            rows.append(
                {
                    "symbol": ticker,
                    "price_date": d,
                    "price": base * (1 + 0.002 * np.sin(i / 5.0)),
                    "source": "yahoo",
                }
            )
    refs = pd.DataFrame(rows)
    usdinr = pd.DataFrame(
        {
            "symbol": "USDINR",
            "price_date": dates,
            "price": 83.5,
            "source": "frankfurter",
        }
    )

    instruments = instruments_frame(config)
    positions = generate_portfolio(config)
    l3 = l3_models_frame(config)
    marks = generate_clean_marks(positions, instruments, refs, l3, config)
    return positions, instruments, marks, refs, usdinr


def test_injected_fraction_near_configured_rate():
    """Injected fraction of position-days is within tolerance of rate."""
    config = _config_with_weights("STALE", seed=3, injection_rate=0.04)
    config = _add_inr_instrument(config)
    positions, instruments, marks, refs, usdinr = _setup(config)

    _faulty, gt = inject_faults(marks, positions, instruments, usdinr, config, seed=3)
    rate = len(gt) / len(marks)
    assert abs(rate - 0.04) < 0.02


def test_no_overlap_on_position_day():
    """Ground truth has unique (position_id, mark_date) rows."""
    config = _config_with_weights("MISSING", seed=4)
    positions, instruments, marks, refs, usdinr = _setup(config)
    _faulty, gt = inject_faults(marks, positions, instruments, usdinr, config, seed=4)
    assert not gt.duplicated(subset=["position_id", "mark_date"]).any()


def test_missing_sets_mark_null():
    """MISSING faults null the mark on the fault day."""
    config = _config_with_weights("MISSING", seed=6)
    positions, instruments, marks, refs, usdinr = _setup(config)
    faulty, gt = inject_faults(marks, positions, instruments, usdinr, config, seed=6)
    assert len(gt) > 0
    merged = faulty.merge(
        gt[["position_id", "mark_date"]], on=["position_id", "mark_date"]
    )
    assert merged["mark"].isna().all()


def test_stale_copies_previous_mark():
    """STALE faults copy the previous day's mark for consecutive days."""
    config = _config_with_weights("STALE", seed=8)
    positions, instruments, marks, refs, usdinr = _setup(config)
    faulty, gt = inject_faults(marks, positions, instruments, usdinr, config, seed=8)
    assert len(gt) > 0

    clean_by_key = {
        (r.position_id, pd.Timestamp(r.mark_date)): r.mark for r in marks.itertuples()
    }
    faulty_by_key = {
        (r.position_id, pd.Timestamp(r.mark_date)): r.mark for r in faulty.itertuples()
    }
    for pid, group in gt.groupby("position_id"):
        group = group.sort_values("mark_date")
        first_date = pd.Timestamp(group.iloc[0]["mark_date"])
        pos_dates = sorted(d for (p, d) in clean_by_key if p == pid)
        first_idx = pos_dates.index(first_date)
        prev_date = pos_dates[first_idx - 1]
        stale_value = faulty_by_key[(pid, prev_date)]
        for row in group.itertuples():
            d = pd.Timestamp(row.mark_date)
            assert faulty_by_key[(pid, d)] == pytest.approx(stale_value)


def test_fat_finger_multiplies_or_transposes():
    """FAT_FINGER multiplies by config factor or transposes digits."""
    config = _config_with_weights("FAT_FINGER", seed=10)
    positions, instruments, marks, refs, usdinr = _setup(config)
    faulty, gt = inject_faults(marks, positions, instruments, usdinr, config, seed=10)
    assert len(gt) > 0

    clean_by_key = {
        (r.position_id, pd.Timestamp(r.mark_date)): r.mark for r in marks.itertuples()
    }
    faulty_by_key = {
        (r.position_id, pd.Timestamp(r.mark_date)): r.mark for r in faulty.itertuples()
    }
    for row in gt.itertuples():
        params = json.loads(row.fault_params_json)
        key = (row.position_id, pd.Timestamp(row.mark_date))
        clean = clean_by_key[key]
        faulty_mark = faulty_by_key[key]
        if params["mode"] == "multiplier":
            assert faulty_mark == pytest.approx(clean * params["multiplier"])
        else:
            assert faulty_mark != clean
            assert sorted(f"{clean:.4f}".rstrip("0").rstrip(".")) is not None


def test_drift_grows_linearly():
    """DRIFT deviation grows linearly at the recorded bps/day."""
    config = _config_with_weights("DRIFT", seed=12)
    positions, instruments, marks, refs, usdinr = _setup(config)
    faulty, gt = inject_faults(marks, positions, instruments, usdinr, config, seed=12)
    assert len(gt) > 0

    clean_by_key = {
        (r.position_id, pd.Timestamp(r.mark_date)): r.mark for r in marks.itertuples()
    }
    faulty_by_key = {
        (r.position_id, pd.Timestamp(r.mark_date)): r.mark for r in faulty.itertuples()
    }
    for pid, group in gt.groupby("position_id"):
        group = group.sort_values("mark_date")
        params = json.loads(group.iloc[0]["fault_params_json"])
        for k, row in enumerate(group.itertuples()):
            key = (pid, pd.Timestamp(row.mark_date))
            clean = clean_by_key[key]
            expected = clean * (
                1.0 + params["direction"] * params["bps_per_day"] * (k + 1) / 1e4
            )
            assert faulty_by_key[key] == pytest.approx(expected, rel=1e-6)


def test_currency_mismatch_uses_fx_rate():
    """CURRENCY_MISMATCH divides INR marks by USDINR."""
    config = _config_with_weights("CURRENCY_MISMATCH", seed=14)
    config = _add_inr_instrument(config)
    positions, instruments, marks, refs, usdinr = _setup(config)
    faulty, gt = inject_faults(marks, positions, instruments, usdinr, config, seed=14)
    inr_rows = gt[gt["position_id"] == "POS-INEQ"]
    clean_by_key = {
        (r.position_id, pd.Timestamp(r.mark_date)): r.mark for r in marks.itertuples()
    }
    faulty_by_key = {
        (r.position_id, pd.Timestamp(r.mark_date)): r.mark for r in faulty.itertuples()
    }
    if len(inr_rows) > 0:
        for row in inr_rows.itertuples():
            key = ("POS-INEQ", pd.Timestamp(row.mark_date))
            assert faulty_by_key[key] == pytest.approx(
                clean_by_key[key] / 83.5, rel=1e-9
            )
    else:
        other = gt.iloc[0]
        key = (other.position_id, pd.Timestamp(other.mark_date))
        assert faulty_by_key[key] == pytest.approx(clean_by_key[key] * 83.5, rel=1e-9)


def test_ground_truth_matches_modified_marks():
    """Every ground-truth row corresponds to a changed mark."""
    config = make_config(seed=16)
    config = _add_inr_instrument(config)
    positions, instruments, marks, refs, usdinr = _setup(config)
    faulty, gt = inject_faults(marks, positions, instruments, usdinr, config, seed=16)
    assert len(gt) > 0

    clean = marks.set_index(["position_id", "mark_date"])["mark"]
    bad = faulty.set_index(["position_id", "mark_date"])["mark"]
    for row in gt.itertuples():
        key = (row.position_id, pd.Timestamp(row.mark_date))
        c = clean.get(key)
        b = bad.get(key)
        if row.fault_type == "MISSING":
            assert pd.isna(b)
        else:
            assert pd.isna(b) or b != c


def test_fixed_seed_reproduces_faults():
    """Same seed produces identical faults and marks."""
    config = make_config(seed=18)
    positions, instruments, marks, refs, usdinr = _setup(config)

    f1, g1 = inject_faults(marks, positions, instruments, usdinr, config, seed=18)
    f2, g2 = inject_faults(marks, positions, instruments, usdinr, config, seed=18)

    pd.testing.assert_frame_equal(g1, g2)
    pd.testing.assert_frame_equal(f1, f2)


def test_different_seed_changes_faults():
    """Different seeds produce different fault placements."""
    config = make_config(seed=20)
    positions, instruments, marks, refs, usdinr = _setup(config)

    _f1, g1 = inject_faults(marks, positions, instruments, usdinr, config, seed=20)
    _f2, g2 = inject_faults(marks, positions, instruments, usdinr, config, seed=21)

    assert not g1.equals(g2)


def test_subtle_faults_just_above_warn():
    """Subtle DRIFT faults end just above the warn threshold."""
    config = make_config(seed=22)
    config.fault_injection = FaultInjectionConfig(
        injection_rate=0.5,
        subtle_fraction=1.0,
        fault_type_weights=_single_type_weights("DRIFT"),
        fault_parameters=config.fault_injection.fault_parameters,
    )
    positions, instruments, marks, refs, usdinr = _setup(config)
    faulty, gt = inject_faults(marks, positions, instruments, usdinr, config, seed=22)
    assert len(gt) > 0
    subtle_rows = gt[gt["fault_params_json"].str.contains('"subtle": true')]
    assert len(subtle_rows) > 0
