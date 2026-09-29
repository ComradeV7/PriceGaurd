"""Guardrails for human-review commentary drafts."""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from priceguard.commentary.template_provider import TemplateProvider

logger = logging.getLogger(__name__)
NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")
BANNED_PHRASES = (
    "approved",
    "approve",
    "adjust the mark",
    "adjust mark",
    "close the exception",
    "closed the exception",
    "resolve the exception",
)


@dataclass(frozen=True)
class GuardrailResult:
    """Guardrail evaluation result."""

    passed: bool
    reason: str | None = None


def _facts_numbers(facts: dict[str, Any]) -> list[float]:
    """Extract numeric leaf values from a facts mapping."""
    values: list[float] = []
    for value in facts.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            values.append(float(value))
        elif isinstance(value, str):
            values.extend(float(token) for token in NUMBER_PATTERN.findall(value))
    return values


def validate_text(
    text: str, facts: dict[str, Any], max_length: int = 500
) -> GuardrailResult:
    """Validate length, banned language and numeric grounding."""
    if len(text) > max_length:
        return GuardrailResult(False, "commentary exceeds maximum length")
    lowered = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            return GuardrailResult(False, f"banned phrase: {phrase}")
    allowed = _facts_numbers(facts)
    for token in NUMBER_PATTERN.findall(text):
        number = float(token)
        if not any(
            abs(number - candidate) <= max(0.01, abs(candidate) * 0.01)
            for candidate in allowed
        ):
            return GuardrailResult(False, f"invented number: {token}")
    return GuardrailResult(True)


def guarded_draft(
    provider: Any,
    facts: dict[str, Any],
    template_provider: TemplateProvider | None = None,
    max_length: int = 500,
) -> tuple[str, GuardrailResult, bool]:
    """Return a draft, falling back to the template on guardrail failure.

    The third return value indicates whether fallback occurred.
    """
    template = template_provider or TemplateProvider()
    try:
        draft = provider.draft(facts)
    except Exception as exc:
        logger.warning("commentary provider failure: %s", exc)
        draft = ""
        result = GuardrailResult(False, f"provider failure: {exc}")
    else:
        result = validate_text(draft, facts, max_length)
    if result.passed:
        return draft, result, False
    logger.warning("guardrail_failure: %s", result.reason)
    fallback = template.draft(facts)
    fallback_result = validate_text(fallback, facts, max_length)
    if not fallback_result.passed:
        logger.warning("template guardrail failure: %s", fallback_result.reason)
    return fallback, GuardrailResult(True, "fallback: " + str(result.reason)), True


def draft_and_store(
    repo,
    exception_id: str,
    facts: dict[str, Any],
    provider: Any,
    template_provider: TemplateProvider | None = None,
    max_length: int = 500,
) -> str:
    """Generate, guard, audit failures, and persist a DRAFT commentary."""
    draft, result, fell_back = guarded_draft(
        provider, facts, template_provider, max_length
    )
    facts_json = json.dumps(facts, sort_keys=True, default=str)
    prompt_hash = hashlib.sha256(facts_json.encode("utf-8")).hexdigest()
    repo.save_commentary(
        exception_id,
        draft,
        provider.provider_name,
        getattr(provider, "model_name", None),
        prompt_hash,
        facts_json,
        result.passed,
    )
    if fell_back:
        repo.write_audit(
            "system",
            "guardrail_failure",
            "commentary",
            exception_id,
            None,
            json.dumps({"reason": result.reason}, sort_keys=True),
        )
    return draft
