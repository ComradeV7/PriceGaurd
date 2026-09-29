# Design Decisions

- Use `uv` as the project environment and dependency runner.
- `instrument_id` and `position_id` are derived from the ticker
  (`EQ1`, `POS-EQ1`); simple and deterministic for a single-position-per-
  instrument synthetic portfolio.
- Yield interpolation outside the FRED tenor range (2/5/10/30y) uses flat
  extrapolation to the nearest tenor rather than sloped extrapolation.
- Bond pricing uses semiannual coupons by default, actual/365.25 day count
  for remaining maturity, and whole-period discounting (no accrued-interest
  split); prices are full DCF values, sufficient for a control demonstrator.
- Level 3 model values and bands are declared in `universe.yaml`
  (`model_value`, `model_band_pct`) and persisted in an `l3_models` table
  (schema extension beyond Section 4.6).
- Business days are the union of dates present in the reference data
  (simple calendar); per-instrument missing days surface via MISSING_MARK.
- Subtle faults (just above warn tolerance) are implemented by forcing
  DRIFT-type events for the subtle bucket, calibrated to end ~10% above
  the warn threshold for the instrument's class; other fault types cannot
  be made "subtle" meaningfully.
- CURRENCY_MISMATCH injection: INR-denominated marks are divided by
  USDINR; other currencies' marks are multiplied by USDINR (mirrors the
  "recorded in the wrong currency" failure mode).
- Faults never overlap on the same position-day; adjacent-day events are
  allowed, so a STALE copy may read an already-faulted previous value
  (ground truth still records every affected day).
- ReturnOutlierCheck uses a rolling window of the last `window_days`
  trading dates pooled across all positions to compute median/MAD of the
  mark-vs-reference return gap; pooling keeps volatile days quiet.
- Exception severity ladder: PASS < WARN < BREACH < CRITICAL with
  CRITICAL at `breach * critical_multiple` (5x by default).
- `upsert_exceptions` preserves workflow columns (status, resolved_date,
  assigned_to, resolution_note, opened_date) on re-run; only
  validation-derived fields are refreshed. Exception IDs are
  sha256(mark_date|position_id|check_name) truncated to 32 chars.
- Schema versioning is migration-free: a `schema_version` table is stamped
  at creation; any change requires recreating the demo database.
- Boundary comparisons use plain `>=` on bps; tests use `np.nextafter`
  where exact float representation of a threshold is required.
- The validation engine and checks never read `ground_truth`; a unit test
  asserts the engine/checks sources do not reference it.
- Workflow simulation is explicitly marked with `exceptions.is_simulated=1`
  and emits a warning; simulated activity is never presented as human review.
- Backtest matching is at position-day level, so multiple checks on one
  injected day count as one detection; STALE/DRIFT lag is measured from the
  first injected day to the first detection on or after it.
- Commentary providers receive only a facts dictionary. Guardrail failures
  produce a deterministic template fallback and an audit event named
  `guardrail_failure`; all stored drafts remain `review_state=DRAFT`.
- Excel exports use openpyxl for workbook creation and a stable 15-column
  review CSV; Power BI outputs use stable dimension/fact CSV names plus a
  committed schema description.
