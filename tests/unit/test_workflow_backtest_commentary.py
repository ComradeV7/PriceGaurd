"""Tests for workflow, backtest, commentary and review behavior."""

from datetime import date

import pandas as pd
import pytest

from priceguard.backtest.metrics import (
    calculate_metrics,
    detection_lag,
    threshold_sweep,
)
from priceguard.commentary.guardrails import guarded_draft, validate_text
from priceguard.commentary.llm_provider import LLMProvider
from priceguard.db.repo import Repository
from priceguard.review.queue import ingest_reviewed_csv
from priceguard.workflow.lifecycle import (
    business_days_between,
    transition_exception,
)
from priceguard.workflow.simulate import simulate_workflow


def seed_exception(repo: Repository, exception_id: str = "E1") -> None:
    """Seed one valid exception and its foreign keys."""
    repo.insert_dataframe(
        "instruments",
        pd.DataFrame(
            [
                {
                    "instrument_id": "I1",
                    "ticker": "I1",
                    "name": "Instrument",
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
                    "position_id": "P1",
                    "instrument_id": "I1",
                    "book": "Trading-A",
                    "quantity": 10,
                    "currency": "USD",
                }
            ]
        ),
    )
    repo.insert_validation_run("R1", "2024-01-02", "hash", 1, 1)
    repo.upsert_exceptions(
        pd.DataFrame(
            [
                {
                    "exception_id": exception_id,
                    "run_id": "R1",
                    "position_id": "P1",
                    "mark_date": "2024-01-02",
                    "check_name": "PRICE_DEVIATION",
                    "severity": "BREACH",
                    "mark": 101.0,
                    "reference_price": 100.0,
                    "deviation_bps": 100.0,
                    "mv_impact_usd": 10.0,
                    "suspected_cause": None,
                    "opened_date": "2024-01-02",
                    "is_primary": 1,
                    "is_material": 0,
                }
            ]
        )
    )


def test_lifecycle_rejects_illegal_transition_and_requires_closure_note():
    """Only allowed transitions and properly evidenced closure are accepted."""
    with Repository(":memory:") as repo:
        seed_exception(repo)
        with pytest.raises(ValueError, match="Illegal transition"):
            transition_exception(repo, "E1", "RESOLVED", "reviewer", "note")
        transition_exception(repo, "E1", "UNDER_REVIEW", "reviewer")
        with pytest.raises(ValueError, match="reviewer and note"):
            transition_exception(repo, "E1", "RESOLVED", "reviewer")
        transition_exception(repo, "E1", "RESOLVED", "reviewer", "Checked source")
        assert len(repo.query("SELECT * FROM audit_log")) == 2


def test_business_age_skips_weekends():
    """Friday to Monday is one business day, not three calendar days."""
    assert business_days_between(date(2024, 1, 5), date(2024, 1, 8)) == 1


def test_simulation_marks_rows_and_warns(caplog):
    """Simulated progression marks rows and writes an audit event."""
    with Repository(":memory:") as repo:
        seed_exception(repo)
        changed = simulate_workflow(repo, seed=1, fraction=1.0, as_of=date(2024, 1, 8))
        assert changed == 1
        row = repo.query("SELECT * FROM exceptions").iloc[0]
        assert row["is_simulated"] == 1
        assert row["status"] == "UNDER_REVIEW"
        assert "simulat" in caplog.text.lower()
        assert len(repo.query("SELECT * FROM audit_log")) == 1


def test_backtest_known_tp_fp_fn_and_lag():
    """Metrics match a hand-built TP/FP/FN case and calculate lag."""
    gt = pd.DataFrame(
        [
            {"position_id": "P1", "mark_date": "2024-01-02", "fault_type": "STALE"},
            {"position_id": "P2", "mark_date": "2024-01-03", "fault_type": "DRIFT"},
            {"position_id": "P3", "mark_date": "2024-01-03", "fault_type": "MISSING"},
        ]
    )
    exceptions = pd.DataFrame(
        [
            {
                "position_id": "P1",
                "mark_date": "2024-01-03",
                "check_name": "STALE_MARK",
            },
            {
                "position_id": "P4",
                "mark_date": "2024-01-03",
                "check_name": "PRICE_DEVIATION",
            },
        ]
    )
    marks = pd.DataFrame(
        [
            {"position_id": p, "mark_date": f"2024-01-0{d}"}
            for p in ["P1", "P2", "P3", "P4"]
            for d in [2, 3]
        ]
    )
    metrics = calculate_metrics(gt, exceptions, marks)
    assert metrics["true_positive"] == 0
    assert metrics["false_positive"] == 2
    assert metrics["false_negative"] == 3
    assert metrics["precision"] == 0
    lag = detection_lag(gt, exceptions)
    assert lag.loc[lag["fault_type"] == "STALE", "lag_days"].iloc[0] == 1


def test_threshold_sweep_recall_is_monotonic_as_threshold_tightens():
    """Lower threshold multipliers cannot reduce detections."""
    observations = pd.DataFrame(
        [
            {"position_id": "P1", "mark_date": "2024-01-01", "deviation_bps": 60},
            {"position_id": "P2", "mark_date": "2024-01-01", "deviation_bps": 120},
            {"position_id": "P3", "mark_date": "2024-01-01", "deviation_bps": 240},
        ]
    )
    gt = observations.iloc[:2].assign(fault_type="DRIFT")
    result = threshold_sweep(observations, gt, [0.5, 1.0, 2.0])
    assert result["recall"].tolist() == sorted(result["recall"].tolist(), reverse=True)


def test_guardrails_reject_numbers_and_banned_language():
    """Invented numbers and approval/adjustment language fail."""
    facts = {"deviation_bps": 312, "mv_impact_usd": 10.0}
    assert not validate_text("The mark is 999 bps away.", facts).passed
    assert not validate_text("The exception is approved.", facts).passed
    assert not validate_text("Adjust the mark now.", facts).passed
    assert validate_text("The mark is 312 bps away.", facts).passed


def test_guarded_draft_falls_back_to_template():
    """A bad provider response falls back and returns a passed result."""

    class BadProvider:
        provider_name = "bad"
        model_name = "test"

        def draft(self, facts):
            return "Approved: adjust the mark to 999."

    facts = {
        "check_name": "PRICE_DEVIATION",
        "deviation_bps": 312,
        "mv_impact_usd": 10.0,
        "suspected_cause": "unknown",
    }
    draft, result, fallback = guarded_draft(BadProvider(), facts)
    assert fallback
    assert result.passed
    assert "312" in draft


def test_llm_provider_is_mockable_and_temperature_zero():
    """Injected client receives the constrained prompt and temperature."""
    calls = {}

    def client(**kwargs):
        calls.update(kwargs)
        return "The cause is unknown."

    text = LLMProvider(client=client, model_name="mock").draft({"value": 1})
    assert text.startswith("The cause")
    assert calls["temperature"] == 0
    assert "Never invent" in calls["system_prompt"]


def test_review_csv_rejects_missing_reviewer_and_applies_valid_rows(tmp_path):
    """CSV ingestion applies valid transitions and reports invalid rows."""
    with Repository(":memory:") as repo:
        seed_exception(repo)
        csv_path = tmp_path / "reviewed_20240102.csv"
        pd.DataFrame(
            [
                {"exception_id": "E1", "status": "UNDER_REVIEW", "Comment": "Checked"},
                {"exception_id": "NOPE", "status": "RESOLVED", "Comment": "No row"},
            ]
        ).to_csv(csv_path, index=False)
        with pytest.raises(ValueError, match="reviewer"):
            ingest_reviewed_csv(repo, csv_path, "")
        result = ingest_reviewed_csv(repo, csv_path, "analyst")
        assert result["applied"] == 1
        assert len(result["invalid"]) == 1
        assert repo.query("SELECT status FROM exceptions").iloc[0, 0] == "UNDER_REVIEW"
