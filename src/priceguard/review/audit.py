"""Audit-log helpers shared by workflow and human review."""

import json

from priceguard.db.repo import Repository


def log_event(
    repo: Repository,
    actor: str,
    action: str,
    entity: str,
    entity_id: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Append a JSON before/after event to audit_log."""
    repo.write_audit(
        actor,
        action,
        entity,
        entity_id,
        json.dumps(before, default=str, sort_keys=True) if before else None,
        json.dumps(after, default=str, sort_keys=True) if after else None,
    )
