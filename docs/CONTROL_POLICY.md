# Control Policy

This document defines the control policies for PriceGuard, including tolerance thresholds, severity rules, review processes, and AI usage guidelines.

> **Note:** All tolerances and thresholds in this document are **illustrative** and for demonstration purposes only. Real-world tolerances require calibration to asset class volatility, materiality thresholds, and regulatory requirements.

---

## Table of Contents

- [Tolerance Thresholds](#tolerance-thresholds)
- [Severity Rules](#severity-rules)
- [Review Process](#review-process)
- [Sign-Off Rules](#sign-off-rules)
- [AI Usage Policy](#ai-usage-policy)
- [Audit Requirements](#audit-requirements)

---

## Tolerance Thresholds

Tolerances define when a mark deviation is considered acceptable (PASS), a warning (WARN), a breach (BREACH), or critical (CRITICAL).

### By Asset Class and Fair Value Level

| Asset Class | FV Level | Warn (bps) | Breach (bps) | Critical (bps) |
|-------------|----------|------------|--------------|----------------|
| Equity | 1 (L1) | 50 | 100 | 500 (5× breach) |
| Bond ETF | 1 (L1) | 75 | 150 | 750 (5× breach) |
| FX | 1 (L1) | 25 | 50 | 250 (5× breach) |
| Bond (L2) | 2 (L2) | 30 | 75 | 375 (5× breach) |
| Private (L3) | 3 (L3) | N/A | N/A | N/A (model band only) |

**Rationale:**

- **Equity (50/100 bps)**: Liquid markets with tight bid-ask spreads. Small deviations indicate potential errors.
- **Bond ETF (75/150 bps)**: Slightly wider than equities due to lower liquidity and model pricing.
- **FX (25/50 bps)**: Very tight tolerances due to high liquidity and electronic trading.
- **Bond L2 (30/75 bps)**: Model-priced bonds have wider tolerances due to yield curve interpolation.
- **L3 (model band)**: No independent price; use model band (±5%) and daily move limits (±2%).

### Critical Multiple

All asset classes use a **critical multiple of 5×** the breach threshold.

**Rationale:** Critical exceptions indicate severe errors (e.g., fat fingers, currency mismatches) that require immediate escalation.

### Special Checks

| Check | Threshold | Severity |
|-------|-----------|----------|
| MISSING_MARK | Any missing mark | CRITICAL |
| FAT_FINGER | Ratio ≈ 10, 100, 0.1, 0.01 | CRITICAL |
| CURRENCY_MISMATCH | Ratio ≈ FX rate | CRITICAL |
| STALE_MARK | Mark unchanged ≥ 2 days while ref moves ≥ 20 bps | WARN/BREACH |
| DRIFT_TREND | Deviation > warn for ≥ 3 consecutive days | WARN/BREACH |
| RETURN_OUTLIER | Return gap > 5× MAD | WARN |
| L3_MODEL_BAND | Mark outside ±5% band | BREACH |
| L3_DAILY_MOVE | Daily move > ±2% | WARN |

---

## Severity Rules

### Severity Levels

| Level | Definition | Action Required |
|-------|------------|-----------------|
| **PASS** | Deviation < warn threshold | No action |
| **WARN** | Warn ≤ deviation < breach | Review within 5 business days |
| **BREACH** | Breach ≤ deviation < critical | Review within 2 business days |
| **CRITICAL** | Deviation ≥ critical | Immediate review and escalation |

### Severity Assignment

```python
if abs(deviation_bps) >= breach_bps * critical_multiple:
    severity = "CRITICAL"
elif abs(deviation_bps) >= breach_bps:
    severity = "BREACH"
elif abs(deviation_bps) >= warn_bps:
    severity = "WARN"
else:
    severity = "PASS"
```

### Special Cases

- **MISSING_MARK**: Always CRITICAL (data integrity issue)
- **FAT_FINGER**: Always CRITICAL (obvious error)
- **CURRENCY_MISMATCH**: Always CRITICAL (obvious error)
- **STALE_MARK**: WARN if ref move < 2× threshold, BREACH otherwise
- **DRIFT_TREND**: WARN if deviation < breach, BREACH otherwise

---

## Review Process

### Workflow States

```
OPEN → UNDER_REVIEW → RESOLVED
                    → ADJUSTED
                    → ESCALATED → UNDER_REVIEW
                                → RESOLVED
                                → ADJUSTED
```

### State Transitions

| From | To | Allowed? | Requirements |
|------|----|----------|--------------|
| OPEN | UNDER_REVIEW | ✅ | Reviewer assigned |
| UNDER_REVIEW | RESOLVED | ✅ | Reviewer, note, sign-off |
| UNDER_REVIEW | ADJUSTED | ✅ | Reviewer, note, sign-off |
| UNDER_REVIEW | ESCALATED | ✅ | Reviewer, escalation reason |
| ESCALATED | UNDER_REVIEW | ✅ | Senior reviewer assigned |
| ESCALATED | RESOLVED | ✅ | Senior reviewer, note, sign-off |
| ESCALATED | ADJUSTED | ✅ | Senior reviewer, note, sign-off |
| RESOLVED | * | ❌ | Terminal state |
| ADJUSTED | * | ❌ | Terminal state |

### Review Timelines

| Severity | Review Deadline | Escalation Deadline |
|----------|-----------------|---------------------|
| WARN | 5 business days | 10 business days |
| BREACH | 2 business days | 5 business days |
| CRITICAL | Immediate | 1 business day |

### Reviewer Roles

| Role | Permissions |
|------|-------------|
| **Analyst** | Review WARN/BREACH, add notes, resolve |
| **Senior Analyst** | Review CRITICAL, escalate, approve adjustments |
| **Manager** | Approve escalated items, sign-off on material impacts |

---

## Sign-Off Rules

### Required Fields for Closure

To transition to **RESOLVED** or **ADJUSTED**, the following fields are required:

| Field | Required? | Description |
|-------|-----------|-------------|
| **Reviewer** | ✅ | Name of person reviewing |
| **Reviewed Date** | ✅ | Date of review |
| **Comment** | ✅ | Explanation of resolution |
| **Sign-off** | ✅ | "Yes" or "No" |

### Validation Rules

```python
def validate_sign_off(exception):
    if exception.status in ["RESOLVED", "ADJUSTED"]:
        if not exception.reviewer:
            raise ValueError("Reviewer is required")
        if not exception.reviewed_date:
            raise ValueError("Reviewed date is required")
        if not exception.comment:
            raise ValueError("Comment is required")
```

### Materiality Threshold

Exceptions with **absolute MV impact > $10,000** are considered **material** and require:

- Senior analyst or manager review
- Detailed comment explaining root cause
- Manager sign-off

---

## AI Usage Policy

### What AI Can Do

✅ **Draft commentary** based on structured facts
✅ **Suggest suspected causes** (e.g., "possible currency mismatch")
✅ **Summarize exception details** for human review
✅ **Generate template text** for common scenarios

### What AI Cannot Do

❌ **Approve exceptions** (human decision only)
❌ **Adjust marks** (human decision only)
❌ **Close exceptions** (human decision only)
❌ **Escalate exceptions** (human decision only)
❌ **Access ground truth** (backtest module only)

### Guardrails

All AI-generated commentary must pass:

1. **Numeric grounding**: Every number in text must appear in facts (±1% tolerance)
2. **Banned phrases**: No "approved", "adjust the mark", "close the exception"
3. **Length limit**: Max 500 characters
4. **Fallback**: On failure, use deterministic template

### Audit Requirements

Every AI action must be logged:

```json
{
  "exception_id": "abc123",
  "provider": "llm",
  "model": "gpt-4o-mini",
  "prompt_hash": "sha256:...",
  "facts": {...},
  "draft_text": "...",
  "guardrail_passed": true,
  "review_state": "DRAFT",
  "timestamp": "2024-03-31T12:00:00Z"
}
```

### Human Review

- AI drafts are labeled as **DRAFT**
- Humans must review and change state to **APPROVED** or **EDITED**
- Final text is stored separately from AI draft
- All human edits are logged in audit trail

---

## Audit Requirements

### What Must Be Logged

Every state change must be logged with:

| Field | Description |
|-------|-------------|
| **event_ts** | Timestamp (UTC) |
| **actor** | User or system (e.g., "analyst_jdoe", "SIMULATOR") |
| **action** | Action taken (e.g., "STATUS_TRANSITION", "COMMENTARY_APPROVED") |
| **entity** | Entity type (e.g., "exception", "commentary") |
| **entity_id** | Entity ID (e.g., exception_id) |
| **before_json** | State before action (JSON) |
| **after_json** | State after action (JSON) |

### Audit Log Examples

**Status transition:**

```json
{
  "event_ts": "2024-03-31T12:00:00Z",
  "actor": "analyst_jdoe",
  "action": "STATUS_TRANSITION",
  "entity": "exception",
  "entity_id": "abc123",
  "before_json": {"status": "OPEN"},
  "after_json": {"status": "UNDER_REVIEW", "reviewer": "analyst_jdoe"}
}
```

**Commentary approval:**

```json
{
  "event_ts": "2024-03-31T12:05:00Z",
  "actor": "analyst_jdoe",
  "action": "COMMENTARY_APPROVED",
  "entity": "commentary",
  "entity_id": "abc123",
  "before_json": {"review_state": "DRAFT"},
  "after_json": {"review_state": "APPROVED", "reviewer": "analyst_jdoe"}
}
```

**Guardrail failure:**

```json
{
  "event_ts": "2024-03-31T12:10:00Z",
  "actor": "system",
  "action": "guardrail_failure",
  "entity": "commentary",
  "entity_id": "abc123",
  "before_json": null,
  "after_json": {"reason": "invented number: 999"}
}
```

### Retention

- Audit logs are retained indefinitely in the SQLite database
- Logs are immutable (INSERT only, no UPDATE/DELETE)
- Logs can be exported for compliance reviews

---

## Compliance Notes

### Regulatory Considerations

This system demonstrates concepts relevant to:

- **Basel III/IV**: Market risk valuation controls
- **IFRS 13**: Fair value measurement hierarchy
- **SOX**: Internal controls over financial reporting
- **MiFID II**: Transaction reporting and valuation

### Disclaimer

This is a **demonstration project** and does not meet regulatory requirements for production use. Real IPV systems require:

- Independent validation by qualified personnel
- Calibration to specific asset classes and markets
- Integration with trading and risk systems
- Regulatory approval and audit
- Disaster recovery and business continuity

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2024-03-31 | Initial policy document |

---

## Questions?

For questions about this control policy, please open an issue on GitHub or contact the project maintainers.
