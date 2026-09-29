"""Tests for the Level 2 bond pricer and yield interpolation."""

from datetime import date

import pandas as pd
import pytest

from priceguard.pricing.bond_pricer import (
    interpolate_yield,
    price_bond,
    price_bond_series,
)


def test_par_bond_at_yield_equals_coupon_prices_at_par():
    """Par bond priced at yield equal to coupon returns face value."""
    price = price_bond(
        face_value=100.0,
        coupon_rate=0.05,
        maturity_date=date(2030, 6, 30),
        valuation_date=date(2025, 6, 30),
        yield_rate=0.05,
        frequency=2,
    )
    assert price == pytest.approx(100.0, rel=1e-6)


def test_price_decreases_when_yield_rises():
    """Bond price falls as yield rises."""
    low = price_bond(100.0, 0.04, date(2034, 12, 31), date(2024, 12, 31), 0.03)
    high = price_bond(100.0, 0.04, date(2034, 12, 31), date(2024, 12, 31), 0.06)
    assert high < low


def test_annual_frequency_par_bond():
    """Annual-pay par bond at yield=coupon prices at par."""
    price = price_bond(
        100.0, 0.05, date(2030, 12, 31), date(2025, 12, 31), 0.05, frequency=1
    )
    assert price == pytest.approx(100.0, rel=1e-6)


def test_matured_bond_raises():
    """Matured bond raises a clear error."""
    with pytest.raises(ValueError, match="matured"):
        price_bond(100.0, 0.04, date(2024, 1, 1), date(2024, 6, 1), 0.04)


def test_interpolation_exact_at_tenors():
    """Interpolation returns exact tenor yields at tenor points."""
    tenors = {2.0: 0.045, 5.0: 0.042, 10.0: 0.043, 30.0: 0.044}
    for t, y in tenors.items():
        assert interpolate_yield(t, tenors) == pytest.approx(y, abs=1e-12)


def test_interpolation_midpoint():
    """Interpolated yield at midpoint is the average of neighbours."""
    tenors = {2.0: 0.04, 10.0: 0.05}
    assert interpolate_yield(6.0, tenors) == pytest.approx(0.045)


def test_interpolation_flat_outside_range():
    """Outside the tenor range, nearest tenor yield is used."""
    tenors = {2.0: 0.04, 30.0: 0.05}
    assert interpolate_yield(1.0, tenors) == pytest.approx(0.04)
    assert interpolate_yield(40.0, tenors) == pytest.approx(0.05)


def test_interpolation_requires_two_tenors():
    """Fewer than two tenors raises an error."""
    with pytest.raises(ValueError, match="two tenors"):
        interpolate_yield(5.0, {5.0: 0.04})


def test_price_bond_series_daily():
    """Daily series prices every available day before maturity."""
    dates = pd.bdate_range("2024-12-01", "2024-12-31")
    rows = []
    for series, level in [("DGS2", 4.4), ("DGS5", 4.2), ("DGS10", 4.3)]:
        for d in dates:
            rows.append({"symbol": series, "price_date": d, "price": level})
    yields = pd.DataFrame(rows)

    result = price_bond_series(
        face_value=100.0,
        coupon_rate=0.04,
        maturity_date=date(2034, 12, 31),
        yield_series=yields,
        tenor_map={"DGS2": 2, "DGS5": 5, "DGS10": 10},
    )
    assert len(result) == len(dates)
    assert {"price_date", "yield_pct", "price"}.issubset(result.columns)
    assert (result["price"] > 0).all()
