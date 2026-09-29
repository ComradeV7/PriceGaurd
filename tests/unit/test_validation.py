"""Tests for validation checks, severity, impact and the engine."""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from priceguard.db.repo import Repository, make_exception_id
from priceguard.validation.checks import (
    CrossSourceCheck,
    CurrencyMismatchCheck,
    DriftTrendCheck,
    FatFingerCheck,
    L3ModelBandCheck,
    MissingMarkCheck,
    PriceDeviationCheck,
    ReturnOutlierCheck,
    StaleMarkCheck,
)
from priceguard.validation.engine import run_validation
from priceguard.validation.impact import fx_to_usd_rate, mv_impact_usd
from priceguard.validation.severity import severity_from_deviation
from tests.conftest import CONFIG_DIR, make_config, make_panel, random_walk

FX_COLUMNS = {"fx_USDINR": 83.5, "fx_EURUSD": 1.10}


class TestSeverity:
    """Severity mapping from deviation and thresholds."""

    def test_pass_below_warn(self):
        assert severity_from_deviation(49.9, 50, 100, 5) == "PASS"

    def test_warn_boundary_exact(self):
        assert severity_from_deviation(50.0, 50, 100, 5) == "WARN"

    def test_breach_boundary_exact(self):
        assert severity_from_deviation(100.0, 50, 100, 5) == "BREACH"

    def test_critical_boundary_exact(self):
        assert severity_from_deviation(500.0, 50, 100, 5) == "CRITICAL"

    def test_negative_deviation_uses_absolute(self):
        assert severity_from_deviation(-120.0, 50, 100, 5) == "BREACH"


class TestImpact:
    """MV impact calculation and FX conversion."""

    def test_impact_sign_positive(self):
        impact = mv_impact_usd(101.0, 100.0, 1000.0, 1.0)
        assert impact == pytest.approx(1000.0)

    def test_impact_sign_negative(self):
        impact = mv_impact_usd(99.0, 100.0, 1000.0, 1.0)
        assert impact == pytest.approx(-1000.0)

    def test_fx_conversion_inr(self):
        rate = fx_to_usd_rate("INR", {"USDINR": 83.5})
        assert rate == pytest.approx(1.0 / 83.5)

    def test_fx_conversion_direct(self):
        rate = fx_to_usd_rate("EUR", {"EURUSD": 1.10})
        assert rate == pytest.approx(1.10)

    def test_fx_conversion_usd(self):
        assert fx_to_usd_rate("USD", {}) == 1.0

    def test_fx_conversion_missing_raises(self):
        with pytest.raises(ValueError, match="No FX rate"):
            fx_to_usd_rate("JPY", {"USDINR": 83.5})


class TestMissingMarkCheck:
    def test_positive_null_mark(self):
        config = make_config()
        panel = make_panel([None, 100.0], [100.0, 100.0])
        findings = MissingMarkCheck().run(panel, config)
        assert len(findings) == 1
        assert findings[0].severity == "CRITICAL"

    def test_negative_all_marks_present(self):
        config = make_config()
        panel = make_panel([100.0, 100.1], [100.0, 100.0])
        assert MissingMarkCheck().run(panel, config) == []


class TestPriceDeviationCheck:
    def test_negative_within_warn(self):
        config = make_config()
        panel = make_panel([100.20], [100.0])  # 20 bps < 50 warn
        assert PriceDeviationCheck().run(panel, config) == []

    def test_positive_warn(self):
        config = make_config()
        panel = make_panel([100.60], [100.0])  # 60 bps -> WARN
        findings = PriceDeviationCheck().run(panel, config)
        assert len(findings) == 1
        assert findings[0].severity == "WARN"

    def test_boundary_exact_warn(self):
        config = make_config()
        # nextafter guards against binary floating-point representation
        mark = float(np.nextafter(100.5, 200.0))
        panel = make_panel([mark], [100.0])  # exactly 50 bps
        findings = PriceDeviationCheck().run(panel, config)
        assert findings[0].severity == "WARN"

    def test_boundary_just_below_warn(self):
        config = make_config()
        panel = make_panel([100.49], [100.0])  # 49 bps
        assert PriceDeviationCheck().run(panel, config) == []

    def test_boundary_exact_breach(self):
        config = make_config()
        panel = make_panel([101.0], [100.0])  # exactly 100 bps
        findings = PriceDeviationCheck().run(panel, config)
        assert findings[0].severity == "BREACH"

    def test_critical_multiple(self):
        config = make_config()
        panel = make_panel([105.0], [100.0])  # 500 bps = 5x breach
        findings = PriceDeviationCheck().run(panel, config)
        assert findings[0].severity == "CRITICAL"

    def test_fx_class_uses_fx_tolerances(self):
        config = make_config()
        panel = make_panel(
            [1.10 * 1.003], [1.10], asset_class="fx", instrument_id="FX1"
        )  # 30 bps > fx warn 25
        findings = PriceDeviationCheck().run(panel, config)
        assert len(findings) == 1
        assert findings[0].severity == "WARN"

    def test_l2_class_uses_l2_tolerances(self):
        config = make_config()
        panel = make_panel(
            [98.0 * 1.004],
            [98.0],
            asset_class="bond_l2",
            fv_level=2,
            instrument_id="BD2",
        )  # 40 bps > bond_l2 warn 30
        findings = PriceDeviationCheck().run(panel, config)
        assert findings[0].severity == "WARN"

    def test_mv_impact_and_materiality(self):
        config = make_config()
        panel = make_panel(
            [102.0], [100.0], quantity=10000.0
        )  # impact = 2 * 10000 = 20000 > 10000 threshold
        findings = PriceDeviationCheck().run(panel, config)
        assert findings[0].mv_impact_usd == pytest.approx(20000.0)
        assert findings[0].is_material

    def test_mv_impact_currency_conversion(self):
        config = make_config()
        panel = make_panel(
            [2525.0],
            [2500.0],
            quantity=100.0,
            position_currency="INR",
            extra_columns=FX_COLUMNS,
        )
        findings = PriceDeviationCheck().run(panel, config)
        expected = (2525.0 - 2500.0) * 100.0 / 83.5
        assert findings[0].mv_impact_usd == pytest.approx(expected, rel=1e-6)


class TestStaleMarkCheck:
    def test_positive_stale_with_ref_move(self):
        config = make_config()
        panel = make_panel(
            [100.0, 100.0, 100.0], [100.0, 101.0, 102.0]
        )  # ref moved 200 bps while mark frozen
        findings = StaleMarkCheck().run(panel, config)
        assert len(findings) == 3
        assert all(f.suspected_cause == "STALE_MARK" for f in findings)

    def test_negative_marks_track_reference(self):
        config = make_config()
        panel = make_panel([100.0, 101.0, 102.0], [100.0, 101.0, 102.0])
        assert StaleMarkCheck().run(panel, config) == []

    def test_near_threshold_small_ref_move(self):
        config = make_config()
        panel = make_panel(
            [100.0, 100.0, 100.0], [100.0, 100.05, 100.1]
        )  # ref moved 10 bps < 20 threshold
        assert StaleMarkCheck().run(panel, config) == []


class TestFatFingerCheck:
    def test_positive_x10(self):
        config = make_config()
        panel = make_panel([1000.0], [100.0])
        findings = FatFingerCheck().run(panel, config)
        assert len(findings) == 1
        assert findings[0].severity == "CRITICAL"
        assert findings[0].suspected_cause == "FAT_FINGER_X10.0"

    def test_positive_x0_1(self):
        config = make_config()
        panel = make_panel([10.0], [100.0])
        findings = FatFingerCheck().run(panel, config)
        assert findings[0].suspected_cause == "FAT_FINGER_X0.1"

    def test_positive_transposition(self):
        config = make_config()
        panel = make_panel([1243.5], [1234.5])
        findings = FatFingerCheck().run(panel, config)
        assert len(findings) == 1
        assert findings[0].suspected_cause == "FAT_FINGER_TRANSPOSITION"

    def test_negative_small_deviation(self):
        config = make_config()
        panel = make_panel([100.6], [100.0])
        assert FatFingerCheck().run(panel, config) == []

    def test_near_threshold_ratio_outside_tolerance(self):
        config = make_config()
        panel = make_panel([950.0], [100.0])  # ratio 9.5, outside 2% of 10
        findings = FatFingerCheck().run(panel, config)
        assert all(f.suspected_cause != "FAT_FINGER_X10.0" for f in findings)


class TestCurrencyMismatchCheck:
    def test_positive_inr_as_usd(self):
        config = make_config()
        panel = make_panel(
            [8350.0], [100.0], extra_columns=FX_COLUMNS
        )  # ratio 83.5 == USDINR
        findings = CurrencyMismatchCheck().run(panel, config)
        assert len(findings) == 1
        assert findings[0].severity == "CRITICAL"
        assert findings[0].suspected_cause == "CURRENCY_MISMATCH_USDINR"

    def test_positive_inverse_rate(self):
        config = make_config()
        panel = make_panel([100.0 / 83.5], [100.0], extra_columns=FX_COLUMNS)
        findings = CurrencyMismatchCheck().run(panel, config)
        assert len(findings) == 1

    def test_negative_normal_deviation(self):
        config = make_config()
        panel = make_panel([200.0], [100.0], extra_columns=FX_COLUMNS)
        assert CurrencyMismatchCheck().run(panel, config) == []


class TestDriftTrendCheck:
    def test_positive_consecutive_warn_days(self):
        config = make_config()
        marks = [100.0, 100.6, 100.7, 100.8, 100.9]
        refs = [100.0] * 5
        panel = make_panel(marks, refs)
        findings = DriftTrendCheck().run(panel, config)
        assert len(findings) >= 1
        assert findings[0].suspected_cause in (
            "DRIFT_TREND",
            "DRIFT_TREND_SLOPE",
        )

    def test_negative_noise_below_warn(self):
        config = make_config()
        marks = [100.0, 100.1, 99.95, 100.05, 100.0]
        refs = [100.0] * 5
        panel = make_panel(marks, refs)
        assert DriftTrendCheck().run(panel, config) == []

    def test_near_threshold_only_two_days(self):
        config = make_config()
        marks = [100.0, 100.0, 100.6, 100.7, 100.0]
        refs = [100.0] * 5
        panel = make_panel(marks, refs)
        findings = DriftTrendCheck().run(panel, config)
        consecutive = [f for f in findings if f.suspected_cause == "DRIFT_TREND"]
        assert consecutive == []


class TestReturnOutlierCheck:
    def _panel_with_outlier(self, outlier_frac: float) -> pd.DataFrame:
        rng = np.random.default_rng(3)
        frames = []
        dates = pd.bdate_range("2024-01-01", periods=15)
        for p in range(12):
            refs = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.002, 15)))
            marks = refs * (1 + rng.normal(0, 0.0005, 15))
            frames.append(
                make_panel(
                    list(marks),
                    list(refs),
                    start=str(dates[0].date()),
                    position_id=f"POS-{p}",
                    instrument_id="EQ1",
                )
            )
        outlier = frames[0].copy()
        last = len(outlier) - 1
        outlier.loc[outlier.index[last], "mark"] = outlier.loc[
            outlier.index[last], "mark"
        ] * (1 + outlier_frac)
        frames[0] = outlier
        return pd.concat(frames, ignore_index=True)

    def test_positive_large_return_gap(self):
        config = make_config()
        panel = self._panel_with_outlier(0.05)  # 500 bps jump
        findings = ReturnOutlierCheck().run(panel, config)
        assert any(
            f.position_id == "POS-0" and f.suspected_cause == "RETURN_OUTLIER"
            for f in findings
        )

    def test_negative_no_outlier(self):
        config = make_config()
        panel = self._panel_with_outlier(0.0)
        findings = ReturnOutlierCheck().run(panel, config)
        pos0 = [f for f in findings if f.position_id == "POS-0"]
        assert pos0 == []

    def test_near_threshold_small_gap(self):
        config = make_config()
        panel = self._panel_with_outlier(0.0005)  # 5 bps jump
        findings = ReturnOutlierCheck().run(panel, config)
        pos0 = [f for f in findings if f.position_id == "POS-0"]
        assert pos0 == []


class TestL3ModelBandCheck:
    def test_positive_out_of_band(self):
        config = make_config()
        panel = make_panel(
            [1_060_000.0],
            [None],
            asset_class="l3",
            fv_level=3,
            instrument_id="L3A",
            extra_columns={"band_min": 950_000.0, "band_max": 1_050_000.0},
        )
        findings = L3ModelBandCheck().run(panel, config)
        assert len(findings) == 1
        assert findings[0].suspected_cause == "L3_OUT_OF_BAND"

    def test_positive_large_daily_move(self):
        config = make_config()
        panel = make_panel(
            [1_000_000.0, 1_030_000.0],
            [None, None],
            asset_class="l3",
            fv_level=3,
            instrument_id="L3A",
            extra_columns={"band_min": 950_000.0, "band_max": 1_050_000.0},
        )
        findings = L3ModelBandCheck().run(panel, config)
        assert any(f.suspected_cause == "L3_LARGE_DAILY_MOVE" for f in findings)

    def test_negative_within_band(self):
        config = make_config()
        panel = make_panel(
            [1_000_000.0, 1_001_000.0],
            [None, None],
            asset_class="l3",
            fv_level=3,
            instrument_id="L3A",
            extra_columns={"band_min": 950_000.0, "band_max": 1_050_000.0},
        )
        assert L3ModelBandCheck().run(panel, config) == []


class TestCrossSourceCheck:
    def test_positive_sources_disagree(self):
        config = make_config()
        panel = make_panel(
            [100.0], [100.0], extra_columns={"reference_price_alt": 101.0}
        )
        findings = CrossSourceCheck().run(panel, config)
        assert len(findings) == 1
        assert findings[0].suspected_cause == "REFERENCE_QUALITY"

    def test_negative_sources_agree(self):
        config = make_config()
        panel = make_panel(
            [100.0], [100.0], extra_columns={"reference_price_alt": 100.05}
        )
        assert CrossSourceCheck().run(panel, config) == []

    def test_no_alt_column_skips(self):
        config = make_config()
        panel = make_panel([100.0], [100.0])
        assert CrossSourceCheck().run(panel, config) == []


class TestEngine:
    def _seed_repo(self, repo: Repository) -> None:
        repo.insert_dataframe(
            "instruments",
            pd.DataFrame(
                [
                    {
                        "instrument_id": "EQ1",
                        "ticker": "EQ1",
                        "name": "Test Equity",
                        "asset_class": "equity",
                        "currency": "USD",
                        "fv_level": 1,
                        "ref_source": "yahoo",
                        "is_active": 1,
                    }
                ]
            ),
        )
        repo.insert_dataframe(
            "positions",
            pd.DataFrame(
                [
                    {
                        "position_id": "POS-EQ1",
                        "instrument_id": "EQ1",
                        "book": "Trading-A",
                        "quantity": 1000.0,
                        "currency": "USD",
                    }
                ]
            ),
        )
        dates = pd.bdate_range("2024-01-01", periods=3)
        repo.insert_dataframe(
            "reference_prices",
            pd.DataFrame(
                {
                    "instrument_id": "EQ1",
                    "price_date": [d.date().isoformat() for d in dates],
                    "price": [100.0, 100.0, 100.0],
                    "source": "yahoo",
                }
            ),
        )
        repo.insert_dataframe(
            "internal_marks",
            pd.DataFrame(
                {
                    "position_id": "POS-EQ1",
                    "mark_date": [d.date().isoformat() for d in dates],
                    "mark": [100.0, 100.0, 101.0],
                    "mark_currency": "USD",
                }
            ),
        )

    def test_engine_writes_runs_and_exceptions(self):
        config = make_config()
        with Repository(":memory:") as repo:
            self._seed_repo(repo)
            exceptions = run_validation(
                repo,
                config,
                CONFIG_DIR,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            assert len(exceptions) > 0

            runs = repo.query("SELECT * FROM validation_runs")
            assert len(runs) == 1
            assert len(runs.iloc[0]["config_hash"]) == 64

            stored = repo.get_exceptions()
            breach = stored[
                (stored["check_name"] == "PRICE_DEVIATION")
                & (stored["mark_date"] == "2024-01-03")
            ]
            assert len(breach) == 1
            assert breach.iloc[0]["severity"] == "BREACH"
            assert breach.iloc[0]["is_primary"] == 1

    def test_engine_rerun_is_idempotent(self):
        config = make_config()
        with Repository(":memory:") as repo:
            self._seed_repo(repo)
            run_validation(
                repo,
                config,
                CONFIG_DIR,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            first = repo.get_exceptions()
            run_validation(
                repo,
                config,
                CONFIG_DIR,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            second = repo.get_exceptions()
            assert len(first) == len(second)
            expected_id = make_exception_id("2024-01-03", "POS-EQ1", "PRICE_DEVIATION")
            assert expected_id in set(second["exception_id"])

    def test_engine_never_touches_ground_truth(self):
        """Engine source must not reference the ground_truth table."""
        engine_src = Path("src/priceguard/validation/engine.py").read_text(
            encoding="utf-8"
        )
        checks_src = Path("src/priceguard/validation/checks.py").read_text(
            encoding="utf-8"
        )
        assert "ground_truth" not in engine_src.split('"""')[-1]
        assert "get_ground_truth" not in engine_src
        assert "get_ground_truth" not in checks_src


class TestFalsePositiveRate:
    def test_clean_marks_low_false_positive_rate(self):
        """Clean noisy marks produce < 1% false positives per check."""
        config = make_config()
        rng = np.random.default_rng(config.settings.seed)
        n_positions = 50
        n_days = 100
        dates = pd.bdate_range("2024-01-01", periods=n_days)

        frames = []
        for p in range(n_positions):
            refs = random_walk(n_days, 100.0 * (p + 1), seed=1000 + p)
            sigma = config.settings.mark_noise.equity
            marks = refs * (1 + rng.normal(0, sigma, n_days))
            frames.append(
                make_panel(
                    list(marks),
                    list(refs),
                    start=str(dates[0].date()),
                    position_id=f"POS-{p}",
                    extra_columns=FX_COLUMNS,
                )
            )
        panel = pd.concat(frames, ignore_index=True)
        total_days = len(panel)
        assert total_days == n_positions * n_days

        checks = [
            PriceDeviationCheck(),
            StaleMarkCheck(),
            FatFingerCheck(),
            CurrencyMismatchCheck(),
            DriftTrendCheck(),
            ReturnOutlierCheck(),
            MissingMarkCheck(),
        ]
        for check in checks:
            findings = check.run(panel, config)
            rate = len(findings) / total_days
            assert rate < 0.01, f"{check.name}: false-positive rate {rate:.4%} >= 1%"
