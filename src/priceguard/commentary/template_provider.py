"""Deterministic offline commentary provider."""

from typing import Any


class TemplateProvider:
    """Rule-based provider suitable for CI and offline operation."""

    provider_name = "template"
    model_name = "deterministic-template"

    def draft(self, facts: dict[str, Any]) -> str:
        """Draft concise commentary from supplied facts."""
        check = str(facts.get("check_name", "unknown"))
        cause = facts.get("suspected_cause") or "unknown"
        deviation = facts.get("deviation_bps")
        impact = facts.get("mv_impact_usd")
        if check == "MISSING_MARK":
            return "The internal mark is missing. Recommend checking the source feed."
        if check == "L3_MODEL_BAND":
            return (
                f"The Level 3 mark is outside the model band; suspected cause: {cause}."
            )
        return (
            f"The mark is {deviation} bps from the independent price with an "
            f"MV impact of {impact} USD; suspected cause: {cause}. "
            "Recommend checking the source feed."
        )
