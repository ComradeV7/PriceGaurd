"""Severity assignment from deviation and thresholds."""

PASS = "PASS"
WARN = "WARN"
BREACH = "BREACH"
CRITICAL = "CRITICAL"

SEVERITY_RANK = {PASS: 0, WARN: 1, BREACH: 2, CRITICAL: 3}


def severity_from_deviation(
    deviation_bps: float,
    warn_bps: float,
    breach_bps: float,
    critical_multiple: float,
) -> str:
    """Map an absolute deviation in bps to a severity level.

    PASS    -> |dev| < warn
    WARN    -> warn <= |dev| < breach
    BREACH  -> breach <= |dev| < breach * critical_multiple
    CRITICAL-> |dev| >= breach * critical_multiple
    """
    dev = abs(deviation_bps)
    critical_bps = breach_bps * critical_multiple
    if dev >= critical_bps:
        return CRITICAL
    if dev >= breach_bps:
        return BREACH
    if dev >= warn_bps:
        return WARN
    return PASS


def max_severity(severities: list[str]) -> str:
    """Return the highest severity from a list."""
    if not severities:
        return PASS
    return max(severities, key=lambda s: SEVERITY_RANK.get(s, 0))
