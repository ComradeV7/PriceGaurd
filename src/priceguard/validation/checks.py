"""Validation checks (Section 5.1).

Each check receives the validation context DataFrame (marks joined with
positions, instruments and reference prices) and the loaded config, and
returns Finding objects. No check reads the ground_truth table.
"""

import numpy as np
import pandas as pd

from priceguard.config import Config
from priceguard.validation.base import Finding, tolerance_for
from priceguard.validation.impact import (
    fx_to_usd_rate,
    is_material,
    mv_impact_usd,
)
from priceguard.validation.severity import (
    BREACH,
    CRITICAL,
    PASS,
    WARN,
    severity_from_deviation,
)

STALE_EPSILON = 1e-9


def _iter_positions(context: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """Group the context panel by position, sorted by date."""
    return [
        (str(pid), g.sort_values("mark_date"))
        for pid, g in context.groupby("position_id", sort=True)
    ]


def _deviation_bps(mark: float, reference: float) -> float:
    """Relative deviation of mark vs reference in basis points."""
    if reference == 0 or pd.isna(reference) or pd.isna(mark):
        return float("nan")
    return (mark / reference - 1.0) * 10_000.0


def _build_finding(
    row: pd.Series,
    check_name: str,
    severity: str,
    deviation_bps: float | None,
    suspected_cause: str | None,
    config: Config,
) -> Finding:
    """Build a Finding with MV impact and materiality computed."""
    mark = row.get("mark")
    ref = row.get("reference_price")
    impact = None
    material = False
    if pd.notna(mark) and pd.notna(ref):
        try:
            fx_rate = fx_to_usd_rate(
                str(row.get("position_currency", "USD")),
                _fx_rate_map(row),
            )
            impact = mv_impact_usd(
                float(mark), float(ref), float(row.get("quantity", 0.0)), fx_rate
            )
            material = is_material(impact, config)
        except ValueError:
            impact = None
    return Finding(
        position_id=str(row["position_id"]),
        mark_date=pd.Timestamp(row["mark_date"]),
        check_name=check_name,
        severity=severity,
        mark=None if pd.isna(mark) else float(mark),
        reference_price=None if pd.isna(ref) else float(ref),
        deviation_bps=deviation_bps,
        mv_impact_usd=impact,
        suspected_cause=suspected_cause,
        is_material=material,
    )


def _fx_rate_map(row: pd.Series) -> dict[str, float]:
    """Build an FX rate lookup from the context row, if present."""
    rates: dict[str, float] = {}
    for col in row.index:
        if isinstance(col, str) and col.startswith("fx_") and pd.notna(row[col]):
            rates[col[3:]] = float(row[col])
    return rates


class MissingMarkCheck:
    """Check 1: mark is null or absent for a position on a business day."""

    name = "MISSING_MARK"

    def run(self, context: pd.DataFrame, config: Config) -> list[Finding]:
        """Flag rows where the internal mark is null."""
        findings = []
        null_rows = context[context["mark"].isna()]
        for _, row in null_rows.iterrows():
            findings.append(
                _build_finding(row, self.name, CRITICAL, None, "MISSING_MARK", config)
            )
        return findings


class PriceDeviationCheck:
    """Check 2: core IPV deviation check against tolerance thresholds."""

    name = "PRICE_DEVIATION"

    def run(self, context: pd.DataFrame, config: Config) -> list[Finding]:
        """Flag marks deviating from reference beyond warn threshold."""
        findings = []
        valid = context[context["mark"].notna() & context["reference_price"].notna()]
        critical_multiple = config.tolerances.severity.critical_multiple
        for _, row in valid.iterrows():
            tol = tolerance_for(str(row["asset_class"]), int(row["fv_level"]), config)
            if tol.warn_bps is None or tol.breach_bps is None:
                continue
            dev = _deviation_bps(float(row["mark"]), float(row["reference_price"]))
            severity = severity_from_deviation(
                dev, tol.warn_bps, tol.breach_bps, critical_multiple
            )
            if severity != PASS:
                findings.append(
                    _build_finding(row, self.name, severity, dev, None, config)
                )
        return findings


class StaleMarkCheck:
    """Check 3: mark unchanged while the reference moved."""

    name = "STALE_MARK"

    def run(self, context: pd.DataFrame, config: Config) -> list[Finding]:
        """Flag marks frozen for min_days while reference moved."""
        min_days = config.tolerances.stale.min_days
        ref_move_bps = config.tolerances.stale.ref_move_bps
        findings = []

        for _pid, group in _iter_positions(context):
            marks = group["mark"].to_numpy(dtype=float)
            refs = group["reference_price"].to_numpy(dtype=float)
            n = len(group)
            run_start = 0
            for i in range(1, n + 1):
                unchanged = (
                    i < n
                    and not np.isnan(marks[i])
                    and not np.isnan(marks[i - 1])
                    and abs(marks[i] - marks[i - 1])
                    <= STALE_EPSILON * max(1.0, abs(marks[i - 1]))
                )
                if not unchanged:
                    run_length = i - run_start
                    if run_length >= min_days:
                        self._emit(
                            group,
                            run_start,
                            i,
                            run_length,
                            refs,
                            ref_move_bps,
                            findings,
                            config,
                        )
                    run_start = i
        return findings

    def _emit(
        self,
        group: pd.DataFrame,
        run_start: int,
        run_end: int,
        run_length: int,
        refs: np.ndarray,
        ref_move_bps: float,
        findings: list[Finding],
        config: Config,
    ) -> None:
        """Emit findings for a stale run if the reference moved enough."""
        ref_slice = refs[run_start:run_end]
        ref_slice = ref_slice[~np.isnan(ref_slice)]
        if len(ref_slice) < 2:
            return
        ref_move = abs(ref_slice[-1] / ref_slice[0] - 1.0) * 10_000.0
        if ref_move < ref_move_bps:
            return
        severity = BREACH if ref_move >= 2 * ref_move_bps else WARN
        for i in range(run_start, run_end):
            row = group.iloc[i]
            findings.append(
                _build_finding(row, self.name, severity, None, "STALE_MARK", config)
            )


class FatFingerCheck:
    """Check 4: order-of-magnitude or digit-transposition errors."""

    name = "FAT_FINGER"
    RATIOS = [10.0, 100.0, 0.1, 0.01]
    REL_TOL = 0.02

    def run(self, context: pd.DataFrame, config: Config) -> list[Finding]:
        """Flag mark/ref ratios near powers of ten or digit swaps."""
        findings = []
        valid = context[
            context["mark"].notna()
            & context["reference_price"].notna()
            & (context["reference_price"] != 0)
        ]
        for _, row in valid.iterrows():
            mark = float(row["mark"])
            ref = float(row["reference_price"])
            ratio = mark / ref
            for target in self.RATIOS:
                if abs(ratio - target) <= self.REL_TOL * target:
                    findings.append(
                        _build_finding(
                            row,
                            self.name,
                            CRITICAL,
                            _deviation_bps(mark, ref),
                            f"FAT_FINGER_X{target}",
                            config,
                        )
                    )
                    break
            else:
                if _is_digit_transposition(mark, ref):
                    findings.append(
                        _build_finding(
                            row,
                            self.name,
                            CRITICAL,
                            _deviation_bps(mark, ref),
                            "FAT_FINGER_TRANSPOSITION",
                            config,
                        )
                    )
        return findings


def _is_digit_transposition(mark: float, ref: float) -> bool:
    """Return True when mark is an adjacent digit swap of ref."""
    ref_text = f"{ref:.2f}"
    digits = [i for i, ch in enumerate(ref_text) if ch.isdigit()]
    if len(digits) < 2:
        return False
    for a, b in zip(digits, digits[1:]):
        chars = list(ref_text)
        chars[a], chars[b] = chars[b], chars[a]
        try:
            candidate = float("".join(chars))
        except ValueError:
            continue
        if candidate != ref and abs(candidate - mark) <= 1e-6 * max(1.0, abs(mark)):
            return True
    return False


class CurrencyMismatchCheck:
    """Check 5: mark quoted in the wrong currency."""

    name = "CURRENCY_MISMATCH"
    REL_TOL = 0.02

    def run(self, context: pd.DataFrame, config: Config) -> list[Finding]:
        """Flag mark/ref ratios matching an FX rate or its inverse."""
        findings = []
        valid = context[
            context["mark"].notna()
            & context["reference_price"].notna()
            & (context["reference_price"] != 0)
        ]
        for _, row in valid.iterrows():
            mark = float(row["mark"])
            ref = float(row["reference_price"])
            ratio = mark / ref
            fx_rates = _fx_rate_map(row)
            for pair, rate in fx_rates.items():
                if rate <= 0:
                    continue
                for target in (rate, 1.0 / rate):
                    if abs(ratio - target) <= self.REL_TOL * target:
                        findings.append(
                            _build_finding(
                                row,
                                self.name,
                                CRITICAL,
                                _deviation_bps(mark, ref),
                                f"CURRENCY_MISMATCH_{pair}",
                                config,
                            )
                        )
                        break
                else:
                    continue
                break
        return findings


class DriftTrendCheck:
    """Check 6: slow-growing deviation, caught before breach."""

    name = "DRIFT_TREND"

    def run(self, context: pd.DataFrame, config: Config) -> list[Finding]:
        """Flag deviations above warn for k consecutive days or a
        significantly positive rolling slope."""
        k = config.tolerances.drift.consecutive_days
        findings = []
        for _pid, group in _iter_positions(context):
            tol = tolerance_for(
                str(group["asset_class"].iloc[0]),
                int(group["fv_level"].iloc[0]),
                config,
            )
            if tol.warn_bps is None:
                continue
            deviations = [
                _deviation_bps(float(row["mark"]), float(row["reference_price"]))
                if pd.notna(row["mark"]) and pd.notna(row["reference_price"])
                else float("nan")
                for _, row in group.iterrows()
            ]
            dev = np.array(deviations, dtype=float)
            above = np.abs(dev) >= tol.warn_bps
            run = 0
            for i, flag in enumerate(above):
                run = run + 1 if flag else 0
                if run == k:
                    severity = (
                        BREACH if abs(dev[i]) >= (tol.breach_bps or np.inf) else WARN
                    )
                    findings.append(
                        _build_finding(
                            group.iloc[i],
                            self.name,
                            severity,
                            float(dev[i]),
                            "DRIFT_TREND",
                            config,
                        )
                    )
            self._slope_flags(group, dev, tol, k, findings, config)
        return findings

    def _slope_flags(
        self,
        group: pd.DataFrame,
        dev: np.ndarray,
        tol: object,
        k: int,
        findings: list[Finding],
        config: Config,
    ) -> None:
        """Flag significantly positive rolling slopes of deviation."""
        window = max(k + 2, 5)
        warn_bps = float(getattr(tol, "warn_bps", 0) or 0)
        if warn_bps <= 0 or len(dev) < window:
            return
        already = {f.mark_date for f in findings if f.check_name == self.name}
        for i in range(window - 1, len(dev)):
            slice_ = dev[i - window + 1 : i + 1]
            if np.isnan(slice_).any():
                continue
            x = np.arange(window, dtype=float)
            slope = float(np.polyfit(x, slice_, 1)[0])
            residual = slice_ - np.polyval(np.polyfit(x, slice_, 1), x)
            rss = float(np.sum(residual**2))
            if slope > 0 and slope * window >= warn_bps and rss < (warn_bps**2) / 4:
                mark_date = pd.Timestamp(group.iloc[i]["mark_date"])
                if mark_date in already:
                    continue
                already.add(mark_date)
                findings.append(
                    _build_finding(
                        group.iloc[i],
                        self.name,
                        WARN,
                        float(slice_[-1]),
                        "DRIFT_TREND_SLOPE",
                        config,
                    )
                )


class ReturnOutlierCheck:
    """Check 7: mark return vs reference return gap, robust threshold.

    Uses a rolling median and MAD of the return gap pooled across all
    positions over the last ``window_days`` trading dates. Pooling
    across the panel keeps volatile days from producing false alarms.
    """

    name = "RETURN_OUTLIER"

    def run(self, context: pd.DataFrame, config: Config) -> list[Finding]:
        """Flag return gaps beyond rolling median +/- mad_multiple*MAD."""
        cfg = config.tolerances.return_outlier
        df = context.copy()
        df = df[df["mark"].notna() & df["reference_price"].notna()]
        if df.empty:
            return []

        df = df.sort_values(["position_id", "mark_date"])
        grouped = df.groupby("position_id", sort=False)
        df["mark_ret_bps"] = grouped["mark"].pct_change() * 10_000.0
        df["ref_ret_bps"] = grouped["reference_price"].pct_change() * 10_000.0
        df["gap_bps"] = df["mark_ret_bps"] - df["ref_ret_bps"]
        df = df.dropna(subset=["gap_bps"])
        if df.empty:
            return []

        dates = sorted(df["mark_date"].unique())
        findings = []
        gaps_by_date = {d: g for d, g in df.groupby("mark_date")}

        for i, mark_date in enumerate(dates):
            window_dates = dates[max(0, i - cfg.window_days + 1) : i + 1]
            pooled = np.concatenate(
                [gaps_by_date[d]["gap_bps"].to_numpy(dtype=float) for d in window_dates]
            )
            if len(pooled) < 5:
                continue
            median = float(np.median(pooled))
            mad = float(np.median(np.abs(pooled - median))) * 1.4826
            threshold = max(cfg.mad_multiple * mad, cfg.min_mad_bps)
            day = gaps_by_date[mark_date]
            for _, row in day.iterrows():
                if abs(float(row["gap_bps"]) - median) > threshold:
                    findings.append(
                        _build_finding(
                            row,
                            self.name,
                            WARN,
                            None,
                            "RETURN_OUTLIER",
                            config,
                        )
                    )
        return findings


class L3ModelBandCheck:
    """Check 8: Level 3 mark outside model band or large daily move."""

    name = "L3_MODEL_BAND"

    def run(self, context: pd.DataFrame, config: Config) -> list[Finding]:
        """Flag L3 marks outside [band_min, band_max] or big daily moves."""
        tol = config.tolerances.l3
        findings = []
        l3 = context[(context["fv_level"] == 3) & context["mark"].notna()]
        if l3.empty:
            return []

        for _pid, group in _iter_positions(l3):
            prev_mark = None
            for _, row in group.iterrows():
                mark = float(row["mark"])
                band_min = row.get("band_min")
                band_max = row.get("band_max")
                if (
                    pd.notna(band_min)
                    and pd.notna(band_max)
                    and not (float(band_min) <= mark <= float(band_max))
                ):
                    findings.append(
                        _build_finding(
                            row,
                            self.name,
                            BREACH,
                            None,
                            "L3_OUT_OF_BAND",
                            config,
                        )
                    )
                if prev_mark is not None and prev_mark != 0:
                    move_pct = abs(mark / prev_mark - 1.0) * 100.0
                    if tol.daily_move_pct is not None and move_pct > tol.daily_move_pct:
                        findings.append(
                            _build_finding(
                                row,
                                self.name,
                                WARN,
                                None,
                                "L3_LARGE_DAILY_MOVE",
                                config,
                            )
                        )
                prev_mark = mark
        return findings


class CrossSourceCheck:
    """Check 9 (optional): two public reference sources disagree.

    Checks reference quality rather than the mark. Requires a context
    with a ``reference_price_alt`` column (alternate source price).
    """

    name = "REFERENCE_CROSS_SOURCE"

    def run(self, context: pd.DataFrame, config: Config) -> list[Finding]:
        """Flag instrument-days where sources disagree beyond threshold."""
        if "reference_price_alt" not in context.columns:
            return []
        max_diff_bps = config.tolerances.cross_source.max_diff_bps
        findings = []
        valid = context[
            context["reference_price"].notna()
            & context["reference_price_alt"].notna()
            & (context["reference_price"] != 0)
        ]
        for _, row in valid.iterrows():
            diff_bps = (
                abs(
                    float(row["reference_price_alt"]) / float(row["reference_price"])
                    - 1.0
                )
                * 10_000.0
            )
            if diff_bps > max_diff_bps:
                findings.append(
                    _build_finding(
                        row,
                        self.name,
                        WARN,
                        float(diff_bps),
                        "REFERENCE_QUALITY",
                        config,
                    )
                )
        return findings


ALL_CHECKS = [
    MissingMarkCheck(),
    PriceDeviationCheck(),
    StaleMarkCheck(),
    FatFingerCheck(),
    CurrencyMismatchCheck(),
    DriftTrendCheck(),
    ReturnOutlierCheck(),
    L3ModelBandCheck(),
    CrossSourceCheck(),
]
