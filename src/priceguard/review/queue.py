"""Human review queue operations and Excel CSV ingestion."""

import json
from pathlib import Path

import pandas as pd

from priceguard.db.repo import Repository
from priceguard.review.audit import log_event
from priceguard.workflow.lifecycle import transition_exception


def list_open_exceptions(repo: Repository) -> pd.DataFrame:
    """List open items by severity rank, then absolute MV impact."""
    result = repo.query(
        "SELECT * FROM exceptions WHERE status NOT IN ('RESOLVED','ADJUSTED')"
    )
    if result.empty:
        return result
    rank = {"CRITICAL": 0, "BREACH": 1, "WARN": 2, "PASS": 3}
    result["_severity_rank"] = result["severity"].map(rank).fillna(99)
    result["_abs_impact"] = result["mv_impact_usd"].abs().fillna(0)
    return result.sort_values(
        ["_severity_rank", "_abs_impact"], ascending=[True, False]
    ).drop(columns=["_severity_rank", "_abs_impact"])


def exception_facts(repo: Repository, exception_id: str) -> dict:
    """Return an exception and its latest commentary facts."""
    rows = repo.query("SELECT * FROM exceptions WHERE exception_id=?", (exception_id,))
    if rows.empty:
        raise ValueError(f"Exception not found: {exception_id}")
    facts = rows.iloc[0].to_dict()
    commentary = repo.query(
        "SELECT draft_text, facts_json, review_state FROM commentary "
        "WHERE exception_id=?",
        (exception_id,),
    )
    if not commentary.empty:
        facts["draft_commentary"] = commentary.iloc[0]["draft_text"]
        facts["commentary_review_state"] = commentary.iloc[0]["review_state"]
        try:
            facts["commentary_facts"] = json.loads(commentary.iloc[0]["facts_json"])
        except (TypeError, json.JSONDecodeError):
            facts["commentary_facts"] = {}
    return facts


def require_reviewer(reviewer: str | None) -> str:
    """Require a non-empty human reviewer name."""
    if not reviewer or not reviewer.strip():
        raise ValueError("reviewer name is required")
    return reviewer.strip()


def approve_draft(repo: Repository, exception_id: str, reviewer: str) -> None:
    """Approve a draft without changing the exception status."""
    reviewer = require_reviewer(reviewer)
    rows = repo.query("SELECT * FROM commentary WHERE exception_id=?", (exception_id,))
    if rows.empty:
        raise ValueError(f"No commentary draft for {exception_id}")
    before = rows.iloc[0].to_dict()
    repo.conn.execute(
        "UPDATE commentary SET review_state='APPROVED', reviewer=?, "
        "reviewed_ts=datetime('now'), final_text=draft_text WHERE exception_id=?",
        (reviewer, exception_id),
    )
    repo.conn.commit()
    after = (
        repo.query("SELECT * FROM commentary WHERE exception_id=?", (exception_id,))
        .iloc[0]
        .to_dict()
    )
    log_event(
        repo, reviewer, "COMMENTARY_APPROVED", "commentary", exception_id, before, after
    )


def edit_draft(repo: Repository, exception_id: str, reviewer: str, text: str) -> None:
    """Save a reviewer-edited draft."""
    reviewer = require_reviewer(reviewer)
    if not text.strip():
        raise ValueError("edited commentary cannot be empty")
    rows = repo.query("SELECT * FROM commentary WHERE exception_id=?", (exception_id,))
    if rows.empty:
        raise ValueError(f"No commentary draft for {exception_id}")
    before = rows.iloc[0].to_dict()
    repo.conn.execute(
        "UPDATE commentary SET review_state='EDITED', reviewer=?, "
        "reviewed_ts=datetime('now'), final_text=? WHERE exception_id=?",
        (reviewer, text, exception_id),
    )
    repo.conn.commit()
    after = (
        repo.query("SELECT * FROM commentary WHERE exception_id=?", (exception_id,))
        .iloc[0]
        .to_dict()
    )
    log_event(
        repo, reviewer, "COMMENTARY_EDITED", "commentary", exception_id, before, after
    )


def set_status(
    repo: Repository,
    exception_id: str,
    status: str,
    reviewer: str,
    note: str | None = None,
) -> dict:
    """Apply a validated reviewer status transition."""
    return transition_exception(
        repo, exception_id, status, require_reviewer(reviewer), note
    )


def add_note(repo: Repository, exception_id: str, reviewer: str, note: str) -> None:
    """Add/update a reviewer note and audit the action."""
    reviewer = require_reviewer(reviewer)
    if not note.strip():
        raise ValueError("note cannot be empty")
    rows = repo.query("SELECT * FROM exceptions WHERE exception_id=?", (exception_id,))
    if rows.empty:
        raise ValueError(f"Exception not found: {exception_id}")
    before = rows.iloc[0].to_dict()
    repo.conn.execute(
        "UPDATE exceptions SET resolution_note=?, assigned_to=? WHERE exception_id=?",
        (note, reviewer, exception_id),
    )
    repo.conn.commit()
    after = (
        repo.query("SELECT * FROM exceptions WHERE exception_id=?", (exception_id,))
        .iloc[0]
        .to_dict()
    )
    log_event(repo, reviewer, "NOTE_ADDED", "exception", exception_id, before, after)


def ingest_reviewed_csv(repo: Repository, csv_path: str | Path, reviewer: str) -> dict:
    """Apply valid reviewed workbook rows and report invalid rows."""
    reviewer = require_reviewer(reviewer)
    frame = pd.read_csv(csv_path)
    applied = 0
    invalid: list[dict] = []
    required = {"exception_id", "status"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Reviewed CSV missing columns: {sorted(missing)}")
    for row_number, row in frame.iterrows():
        exception_id = str(row["exception_id"])
        try:
            status = str(row["status"]).strip()
            note = str(row.get("Comment", row.get("resolution_note", "")))
            if status in {"UNDER_REVIEW", "RESOLVED", "ADJUSTED", "ESCALATED"}:
                set_status(repo, exception_id, status, reviewer, note or None)
            elif status == "OPEN":
                raise ValueError("OPEN is not a reviewer transition")
            else:
                raise ValueError(f"unknown status: {status}")
            applied += 1
        except (ValueError, KeyError) as exc:
            invalid.append(
                {
                    "row": int(row_number) + 2,
                    "exception_id": exception_id,
                    "error": str(exc),
                }
            )
    return {"applied": applied, "invalid": pd.DataFrame(invalid)}
