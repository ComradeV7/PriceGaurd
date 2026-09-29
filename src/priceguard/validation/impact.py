"""Market-value impact calculation with FX conversion."""

from priceguard.config import Config


def fx_to_usd_rate(currency: str, fx_rates: dict[str, float]) -> float:
    """Return the FX rate converting one unit of currency into USD.

    Args:
        currency: Position currency (ISO code).
        fx_rates: Mapping of pair symbol to rate, e.g.
            {"USDINR": 83.5, "EURUSD": 1.10}.

    Returns:
        Multiplicative factor: amount_usd = amount * factor.
    """
    if currency == "USD":
        return 1.0
    direct = fx_rates.get(f"{currency}USD")
    if direct is not None:
        return float(direct)
    inverse = fx_rates.get(f"USD{currency}")
    if inverse is not None and float(inverse) != 0:
        return 1.0 / float(inverse)
    raise ValueError(f"No FX rate available to convert {currency} to USD")


def mv_impact_usd(
    mark: float,
    reference_price: float,
    quantity: float,
    fx_rate_to_usd: float,
) -> float:
    """Signed USD market-value impact of a mark deviation.

    mv_impact_usd = (mark - reference) * quantity * fx_to_usd
    """
    return (mark - reference_price) * quantity * fx_rate_to_usd


def is_material(abs_impact_usd: float, config: Config) -> bool:
    """Return True when the absolute impact exceeds the materiality threshold."""
    return abs(abs_impact_usd) >= config.tolerances.materiality.mv_threshold_usd
