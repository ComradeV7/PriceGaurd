"""Level 2 bond pricing from FRED Treasury yields."""

from datetime import date

import numpy as np
import pandas as pd


def price_bond(
    face_value: float,
    coupon_rate: float,
    maturity_date: date,
    valuation_date: date,
    yield_rate: float,
    frequency: int = 2,
) -> float:
    """Price a fixed-coupon bond by discounted cash flows.

    Args:
        face_value: Par value of the bond.
        coupon_rate: Annual coupon rate as a decimal (e.g. 0.04).
        maturity_date: Date the bond matures.
        valuation_date: Date the bond is priced at.
        yield_rate: Annual yield to maturity as a decimal.
        frequency: Coupon payments per year (1=annual, 2=semiannual).

    Returns:
        Clean price of the bond as a float.

    Raises:
        ValueError: If the bond has matured or inputs are invalid.
    """
    if maturity_date <= valuation_date:
        raise ValueError(
            f"Bond matured on {maturity_date}; cannot price at "
            f"valuation date {valuation_date}"
        )
    if face_value <= 0:
        raise ValueError(f"Face value must be positive, got {face_value}")
    if coupon_rate < 0:
        raise ValueError(f"Coupon rate must be non-negative, got {coupon_rate}")
    if frequency not in (1, 2, 4):
        raise ValueError(f"Frequency must be 1, 2 or 4, got {frequency}")
    if yield_rate <= -1:
        raise ValueError(f"Yield rate must be > -1, got {yield_rate}")

    remaining_days = (maturity_date - valuation_date).days
    remaining_years = remaining_days / 365.25
    n_periods = max(1, int(np.ceil(remaining_years * frequency)))
    period_yield = yield_rate / frequency
    period_coupon = face_value * coupon_rate / frequency

    price = 0.0
    for k in range(1, n_periods + 1):
        discount = (1.0 + period_yield) ** k
        if discount <= 0:
            raise ValueError("Non-positive discount factor; yield too negative")
        price += period_coupon / discount
    price += face_value / (1.0 + period_yield) ** n_periods
    return price


def interpolate_yield(remaining_years: float, tenors: dict[float, float]) -> float:
    """Linearly interpolate a yield between tenor points.

    Args:
        remaining_years: Remaining maturity in years.
        tenors: Mapping of tenor (years) to yield (decimal).

    Returns:
        Interpolated yield. Outside the tenor range, the nearest
        tenor yield is used (flat extrapolation).

    Raises:
        ValueError: If fewer than two tenors are provided or
            remaining_years is not positive.
    """
    if len(tenors) < 2:
        raise ValueError("At least two tenors are required for interpolation")
    if remaining_years <= 0:
        raise ValueError(f"remaining_years must be positive, got {remaining_years}")

    x = np.array(sorted(tenors.keys()), dtype=float)
    y = np.array([tenors[t] for t in x], dtype=float)
    return float(np.interp(remaining_years, x, y))


def price_bond_series(
    face_value: float,
    coupon_rate: float,
    maturity_date: date,
    yield_series: pd.DataFrame,
    tenor_map: dict[str, float],
    frequency: int = 2,
) -> pd.DataFrame:
    """Price a bond daily using an interpolated yield curve.

    Args:
        face_value: Par value of the bond.
        coupon_rate: Annual coupon rate as a decimal.
        maturity_date: Date the bond matures.
        yield_series: Tidy DataFrame with columns symbol, price_date,
            price (yield in percent) for FRED tenor series.
        tenor_map: Mapping of FRED symbol to tenor in years
            (e.g. {"DGS2": 2, "DGS10": 10}).
        frequency: Coupon payments per year.

    Returns:
        DataFrame with columns price_date, yield_pct, price.
    """
    pivoted = yield_series.pivot_table(
        index="price_date", columns="symbol", values="price", aggfunc="last"
    ).sort_index()

    available = [s for s in tenor_map if s in pivoted.columns]
    if len(available) < 2:
        raise ValueError(f"Need at least two tenor series, found {available}")

    records = []
    for price_date, row in pivoted.iterrows():
        valuation_date = (
            price_date.date() if hasattr(price_date, "date") else price_date
        )
        if valuation_date >= maturity_date:
            continue
        tenors = {}
        for symbol in available:
            value = row.get(symbol)
            if pd.notna(value):
                tenors[tenor_map[symbol]] = float(value) / 100.0
        if len(tenors) < 2:
            continue
        remaining_years = (maturity_date - valuation_date).days / 365.25
        y = interpolate_yield(remaining_years, tenors)
        price = price_bond(
            face_value=face_value,
            coupon_rate=coupon_rate,
            maturity_date=maturity_date,
            valuation_date=valuation_date,
            yield_rate=y,
            frequency=frequency,
        )
        records.append(
            {"price_date": price_date, "yield_pct": y * 100.0, "price": price}
        )

    return pd.DataFrame(records)
