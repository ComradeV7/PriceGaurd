"""Tests for synthetic portfolio and clean mark generation."""

import pandas as pd

from priceguard.synth.marks import generate_clean_marks
from priceguard.synth.portfolio import (
    generate_portfolio,
    instruments_frame,
    l3_models_frame,
)
from tests.conftest import make_config


def _reference_prices(config):
    """Deterministic reference panel for the mini universe."""
    dates = pd.bdate_range("2024-12-01", periods=20)
    rows = []
    for ticker, base in [("EQ1", 100.0), ("FX1", 1.10), ("BD2", 98.0)]:
        for i, d in enumerate(dates):
            rows.append(
                {
                    "symbol": ticker,
                    "price_date": d,
                    "price": base * (1 + 0.001 * i),
                    "source": "yahoo",
                }
            )
    return pd.DataFrame(rows)


def test_portfolio_same_seed_identical():
    """Same seed gives identical portfolio."""
    config = make_config(seed=7)
    a = generate_portfolio(config)
    b = generate_portfolio(config)
    pd.testing.assert_frame_equal(a, b)


def test_portfolio_different_seed_differs():
    """Different seeds give different portfolios."""
    a = generate_portfolio(make_config(seed=7))
    b = generate_portfolio(make_config(seed=8))
    assert not a["quantity"].equals(b["quantity"]) or not a["book"].equals(b["book"])


def test_portfolio_one_position_per_instrument():
    """Exactly one position per instrument, quantities in range."""
    config = make_config()
    positions = generate_portfolio(config)
    assert len(positions) == len(config.universe.instruments)
    assert positions["position_id"].is_unique
    for pos in positions.itertuples():
        instrument_id = pos.instrument_id
        asset_class = next(
            i.asset_class
            for i in config.universe.instruments
            if i.ticker == instrument_id
        )
        qty_range = config.settings.portfolio.quantity_ranges[asset_class]
        assert qty_range.min <= pos.quantity <= qty_range.max


def test_marks_same_seed_identical():
    """Same seed gives identical clean marks."""
    config = make_config(seed=11)
    positions = generate_portfolio(config)
    instruments = instruments_frame(config)
    refs = _reference_prices(config)
    l3 = l3_models_frame(config)

    a = generate_clean_marks(positions, instruments, refs, l3, config)
    b = generate_clean_marks(positions, instruments, refs, l3, config)
    pd.testing.assert_frame_equal(a, b)


def test_marks_different_seed_differs():
    """Different seeds give different marks."""
    positions = generate_portfolio(make_config(seed=11))
    instruments = instruments_frame(make_config(seed=11))
    refs = _reference_prices(make_config(seed=11))
    l3 = l3_models_frame(make_config(seed=11))

    a = generate_clean_marks(positions, instruments, refs, l3, make_config(seed=11))
    b = generate_clean_marks(positions, instruments, refs, l3, make_config(seed=12))
    assert not a["mark"].equals(b["mark"])


def test_clean_marks_within_five_sigma():
    """All clean marks fall within 5 sigma of the reference."""
    config = make_config(seed=13)
    positions = generate_portfolio(config)
    instruments = instruments_frame(config)
    refs = _reference_prices(config)
    l3 = l3_models_frame(config)

    marks = generate_clean_marks(positions, instruments, refs, l3, config)
    assert len(marks) > 0

    inst_by_id = instruments.set_index("instrument_id")
    sigma_map = {
        "equity": config.settings.mark_noise.equity,
        "bond_etf": config.settings.mark_noise.bond_etf,
        "fx": config.settings.mark_noise.fx,
        "bond_l2": config.settings.mark_noise.bond_l2,
    }

    checked = 0
    for pos in positions.itertuples():
        instrument = inst_by_id.loc[pos.instrument_id]
        if instrument["asset_class"] == "l3":
            continue
        sigma = sigma_map[instrument["asset_class"]]
        subset = marks[marks["position_id"] == pos.position_id]
        inst_refs = refs[refs["symbol"] == pos.instrument_id].set_index("price_date")[
            "price"
        ]
        for row in subset.itertuples():
            ref = inst_refs.get(row.mark_date)
            if ref is None or pd.isna(ref):
                continue
            deviation = abs(row.mark / ref - 1.0)
            checked += 1
            assert deviation <= 5 * sigma, (
                f"{pos.position_id} {row.mark_date}: {deviation} > 5 sigma"
            )
    assert checked > 0


def test_l3_marks_have_no_reference_and_stay_in_band():
    """L3 marks are a walk around the model value; band is stored."""
    config = make_config(seed=17)
    positions = generate_portfolio(config)
    instruments = instruments_frame(config)
    refs = _reference_prices(config)
    l3 = l3_models_frame(config)

    marks = generate_clean_marks(positions, instruments, refs, l3, config)
    l3_rows = marks[marks["position_id"] == "POS-L3A"]
    assert len(l3_rows) > 0

    model_value = float(l3.set_index("instrument_id").loc["L3A", "model_value"])
    band_pct = 5.0
    deviations = (l3_rows["mark"] / model_value - 1.0).abs() * 100.0
    # A slow walk over 20 days at 0.1% daily sigma stays well inside 5%
    assert (deviations < band_pct).all()
