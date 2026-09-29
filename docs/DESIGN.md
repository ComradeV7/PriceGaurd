# Design Document

This document describes the technical architecture, data flow, and design decisions for PriceGuard.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Data Flow](#data-flow)
- [Database Schema](#database-schema)
- [Validation Engine](#validation-engine)
- [Commentary Layer](#commentary-layer)
- [Workflow Management](#workflow-management)
- [Export System](#export-system)
- [Design Decisions](#design-decisions)

---

## Architecture Overview

PriceGuard follows a **pipeline architecture** with 8 sequential stages:

```
┌─────────────┐
│   Ingest    │  Fetch reference prices from public sources
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Generate   │  Create synthetic portfolio, marks, and faults
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Validate   │  Run 8 checks against marks
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Commentary  │  Draft factual text for exceptions
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Workflow   │  Track exception lifecycle
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Backtest   │  Measure recall/precision
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Export    │  Generate Excel and Power BI outputs
└─────────────┘
```

### Key Design Principles

1. **Separation of concerns**: Each stage is independent and testable
2. **Idempotency**: Re-running stages produces the same results
3. **Auditability**: Every state change is logged
4. **Reproducibility**: Seeded randomness for deterministic results
5. **Guard-railed AI**: AI drafts only, humans decide

---

## Data Flow

### Stage 1: Ingest

**Input:** Universe configuration (config/universe.yaml)
**Output:** Parquet files in data/raw/

**Process:**

1. Read instrument list from universe.yaml
2. For each instrument:
   - Fetch prices from appropriate source (Yahoo, FRED, FX, Stooq)
   - Cache as Parquet file (source_symbol_startdate_enddate.parquet)
3. Print coverage summary

**Data Schema:**

```
symbol: str          # Ticker symbol
price_date: date     # Trading date
price: float         # Closing price
source: str          # Data source (yahoo, fred, frankfurter, stooq)
```

### Stage 2: Generate

**Input:** Parquet files, configuration
**Output:** SQLite database with positions, marks, ground_truth

**Process:**

1. Load all Parquet files into reference_prices table
2. Price L2 bonds using FRED yields and bond_pricer
3. Generate portfolio (one position per instrument)
4. Generate clean marks: `mark = ref × (1 + N(0, σ))`
5. Generate L3 marks: random walk around model value
6. Inject faults (STALE, FAT_FINGER, MISSING, DRIFT, CURRENCY_MISMATCH)
7. Write ground_truth table with fault parameters

**Data Schema:**

```
positions:
  position_id: str
  instrument_id: str
  book: str
  quantity: float
  currency: str

internal_marks:
  position_id: str
  mark_date: date
  mark: float
  mark_currency: str

ground_truth:
  position_id: str
  mark_date: date
  fault_type: str
  fault_params_json: str
```

### Stage 3: Validate

**Input:** internal_marks, reference_prices
**Output:** exceptions table

**Process:**

1. Build context: join marks with positions, instruments, references
2. Run 8 checks:
   - MISSING_MARK: mark is null
   - PRICE_DEVIATION: |mark/ref - 1| > threshold
   - STALE_MARK: mark unchanged while ref moves
   - FAT_FINGER: mark/ref ≈ 10, 100, 0.1, 0.01
   - CURRENCY_MISMATCH: mark/ref ≈ FX rate
   - DRIFT_TREND: deviation > warn for k consecutive days
   - RETURN_OUTLIER: return gap > 5× MAD
   - L3_MODEL_BAND: mark outside ±5% band
3. Assign severity (PASS/WARN/BREACH/CRITICAL)
4. Calculate MV impact: `(mark - ref) × quantity × fx_to_usd`
5. Write exceptions with deterministic IDs

**Data Schema:**

```
exceptions:
  exception_id: str          # sha256(mark_date|position_id|check_name)
  run_id: str
  position_id: str
  mark_date: date
  check_name: str
  severity: str
  mark: float
  reference_price: float
  deviation_bps: float
  mv_impact_usd: float
  suspected_cause: str
  status: str                # OPEN, UNDER_REVIEW, RESOLVED, ADJUSTED, ESCALATED
  opened_date: date
  resolved_date: date
  age_days: int
  assigned_to: str
  resolution_note: str
  is_primary: bool
  is_material: bool
  is_simulated: bool
```

### Stage 4: Commentary

**Input:** exceptions
**Output:** commentary table

**Process:**

1. For each exception, extract facts (mark, ref, deviation, impact, cause)
2. Generate draft text:
   - TemplateProvider: deterministic rules
   - LLMProvider: optional, with guardrails
3. Validate guardrails:
   - Numeric grounding (all numbers in facts)
   - Banned phrases (no approval language)
   - Length limit (500 chars)
4. On failure, fall back to template
5. Write commentary with review_state=DRAFT

**Data Schema:**

```
commentary:
  exception_id: str
  draft_text: str
  provider: str              # template, llm
  model_name: str
  prompt_hash: str
  created_ts: timestamp
  facts_json: str
  guardrail_passed: bool
  review_state: str          # DRAFT, APPROVED, EDITED
  reviewer: str
  reviewed_ts: timestamp
  final_text: str
```

### Stage 5: Workflow

**Input:** exceptions, user actions
**Output:** updated exceptions, audit_log

**Process:**

1. User reviews exception (Excel or CLI)
2. User sets status, adds note, signs off
3. Validate transition rules (see CONTROL_POLICY.md)
4. Update exception status
5. Calculate age_days (business days since opened_date)
6. Write audit_log entry

**State Machine:**

```
OPEN → UNDER_REVIEW → RESOLVED
                    → ADJUSTED
                    → ESCALATED → UNDER_REVIEW
                                → RESOLVED
                                → ADJUSTATED
```

### Stage 6: Backtest

**Input:** exceptions, ground_truth
**Output:** metrics, reports

**Process:**

1. Match exceptions to ground_truth by (position_id, mark_date)
2. Calculate:
   - True positives (detected faults)
   - False positives (exceptions on clean days)
   - False negatives (undetected faults)
3. Calculate recall, precision, FPR
4. Calculate detection lag for STALE/DRIFT
5. Generate reports (CSV, Markdown)

**Metrics:**

```
recall = TP / (TP + FN)
precision = TP / (TP + FP)
false_positive_rate = FP / clean_days
detection_lag = first_detection_date - first_fault_date
```

### Stage 7: Export

**Input:** exceptions, marks, positions
**Output:** Excel CSV/XLSX, Power BI CSVs

**Process:**

1. Export daily exceptions:
   - CSV: daily_exceptions_YYYYMMDD.csv
   - XLSX: daily_exceptions_YYYYMMDD.xlsx (with formatting)
2. Export Power BI star schema:
   - dim_date, dim_instrument, dim_book, dim_severity, dim_status
   - fact_marks, fact_exceptions, fact_backtest
   - schema.json

---

## Database Schema

### Core Tables

```sql
-- Instruments (44 total)
CREATE TABLE instruments (
    instrument_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    currency TEXT NOT NULL,
    fv_level INTEGER NOT NULL,
    ref_source TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

-- Positions (one per instrument)
CREATE TABLE positions (
    position_id TEXT PRIMARY KEY,
    instrument_id TEXT REFERENCES instruments(instrument_id),
    book TEXT NOT NULL,
    quantity REAL NOT NULL,
    currency TEXT NOT NULL
);

-- Reference prices (from public sources)
CREATE TABLE reference_prices (
    instrument_id TEXT REFERENCES instruments(instrument_id),
    price_date TEXT NOT NULL,
    price REAL NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (instrument_id, price_date, source)
);

-- Internal marks (synthetic)
CREATE TABLE internal_marks (
    position_id TEXT REFERENCES positions(position_id),
    mark_date TEXT NOT NULL,
    mark REAL,
    mark_currency TEXT NOT NULL,
    PRIMARY KEY (position_id, mark_date)
);

-- Ground truth (backtest only)
CREATE TABLE ground_truth (
    position_id TEXT REFERENCES positions(position_id),
    mark_date TEXT NOT NULL,
    fault_type TEXT NOT NULL,
    fault_params_json TEXT NOT NULL,
    PRIMARY KEY (position_id, mark_date)
);

-- Exceptions (validation results)
CREATE TABLE exceptions (
    exception_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    position_id TEXT REFERENCES positions(position_id),
    mark_date TEXT NOT NULL,
    check_name TEXT NOT NULL,
    severity TEXT NOT NULL,
    mark REAL,
    reference_price REAL,
    deviation_bps REAL,
    mv_impact_usd REAL,
    suspected_cause TEXT,
    status TEXT DEFAULT 'OPEN',
    opened_date TEXT NOT NULL,
    resolved_date TEXT,
    age_days INTEGER DEFAULT 0,
    assigned_to TEXT,
    resolution_note TEXT,
    is_primary INTEGER DEFAULT 1,
    is_material INTEGER DEFAULT 0,
    is_simulated INTEGER DEFAULT 0
);

-- Commentary (AI drafts)
CREATE TABLE commentary (
    exception_id TEXT REFERENCES exceptions(exception_id),
    draft_text TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_name TEXT,
    prompt_hash TEXT,
    created_ts TEXT NOT NULL,
    facts_json TEXT NOT NULL,
    guardrail_passed INTEGER DEFAULT 1,
    review_state TEXT DEFAULT 'DRAFT',
    reviewer TEXT,
    reviewed_ts TEXT,
    final_text TEXT
);

-- Audit log (immutable)
CREATE TABLE audit_log (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT
);

-- L3 models (model values and bands)
CREATE TABLE l3_models (
    instrument_id TEXT PRIMARY KEY REFERENCES instruments(instrument_id),
    model_value REAL NOT NULL,
    band_min REAL NOT NULL,
    band_max REAL NOT NULL
);

-- Validation runs (metadata)
CREATE TABLE validation_runs (
    run_id TEXT PRIMARY KEY,
    run_ts TEXT NOT NULL,
    mark_date TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    n_positions INTEGER NOT NULL,
    n_exceptions INTEGER NOT NULL
);

-- Schema versioning
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_ts TEXT NOT NULL
);
```

### Indexes

```sql
CREATE INDEX idx_exceptions_mark_date ON exceptions(mark_date);
CREATE INDEX idx_exceptions_status ON exceptions(status);
CREATE INDEX idx_marks_position ON internal_marks(position_id, mark_date);
CREATE INDEX idx_reference_prices_date ON reference_prices(price_date);
```

---

## Validation Engine

### Check Interface

```python
class Check(Protocol):
    name: str
    def run(self, context: pd.DataFrame, config: Config) -> list[Finding]:
        ...
```

### Context DataFrame

The validation context is a joined DataFrame with columns:

```
position_id, mark_date, mark, mark_currency,
instrument_id, book, quantity, position_currency,
ticker, name, asset_class, fv_level, ref_source,
reference_price, reference_source,
fx_USDINR, fx_EURUSD, ...  # FX rates
band_min, band_max          # L3 model bands
```

### Check Implementations

1. **MissingMarkCheck**: `mark.isna()`
2. **PriceDeviationCheck**: `abs(mark/ref - 1) × 10000 > threshold`
3. **StaleMarkCheck**: `mark[t] == mark[t-1]` and `abs(ref[t] - ref[t-n]) > threshold`
4. **FatFingerCheck**: `mark/ref ∈ {10, 100, 0.1, 0.01}` or digit transposition
5. **CurrencyMismatchCheck**: `mark/ref ≈ fx_rate`
6. **DriftTrendCheck**: `deviation > warn` for k consecutive days
7. **ReturnOutlierCheck**: `abs(return_gap - median) > 5 × MAD`
8. **L3ModelBandCheck**: `mark < band_min` or `mark > band_max`

### Severity Assignment

```python
def severity_from_deviation(dev_bps, warn, breach, critical_multiple):
    if abs(dev_bps) >= breach * critical_multiple:
        return "CRITICAL"
    elif abs(dev_bps) >= breach:
        return "BREACH"
    elif abs(dev_bps) >= warn:
        return "WARN"
    else:
        return "PASS"
```

### Exception ID Generation

```python
def make_exception_id(mark_date, position_id, check_name):
    payload = f"{mark_date}|{position_id}|{check_name}"
    return hashlib.sha256(payload.encode()).hexdigest()[:32]
```

This ensures idempotency: re-running validation produces the same exception IDs.

---

## Commentary Layer

### Provider Interface

```python
class CommentaryProvider(Protocol):
    provider_name: str
    model_name: str
    def draft(self, facts: dict) -> str:
        ...
```

### TemplateProvider

Deterministic text generation based on check_name and suspected_cause:

```python
def draft(self, facts):
    check = facts["check_name"]
    cause = facts.get("suspected_cause", "unknown")
    dev = facts["deviation_bps"]
    impact = facts["mv_impact_usd"]
    
    if check == "MISSING_MARK":
        return "The internal mark is missing. Recommend checking the source feed."
    elif check == "PRICE_DEVIATION":
        return f"The mark is {dev} bps from the independent price with an MV impact of {impact} USD; suspected cause: {cause}."
    # ... other checks
```

### LLMProvider

Optional LLM-based provider with guardrails:

```python
def draft(self, facts):
    prompt = f"Draft commentary for exception: {json.dumps(facts)}"
    response = self.client.complete(prompt, temperature=0)
    return response.text
```

### Guardrails

```python
def validate_text(text, facts):
    # 1. Check length
    if len(text) > 500:
        return False, "exceeds length limit"
    
    # 2. Check banned phrases
    banned = ["approved", "adjust the mark", "close the exception"]
    for phrase in banned:
        if phrase in text.lower():
            return False, f"banned phrase: {phrase}"
    
    # 3. Check numeric grounding
    numbers = extract_numbers(text)
    for num in numbers:
        if not any(abs(num - fact_num) < 0.01 * fact_num for fact_num in facts.values()):
            return False, f"invented number: {num}"
    
    return True, None
```

---

## Workflow Management

### State Transitions

```python
ALLOWED_TRANSITIONS = {
    "OPEN": {"UNDER_REVIEW"},
    "UNDER_REVIEW": {"RESOLVED", "ADJUSTED", "ESCALATED"},
    "ESCALATED": {"UNDER_REVIEW", "RESOLVED", "ADJUSTED"},
    "RESOLVED": set(),
    "ADJUSTED": set(),
}

def transition_exception(exception_id, new_status, reviewer, note):
    # Validate transition
    if new_status not in ALLOWED_TRANSITIONS[old_status]:
        raise ValueError(f"Illegal transition: {old_status} -> {new_status}")
    
    # Validate closure requirements
    if new_status in ["RESOLVED", "ADJUSTED"]:
        if not reviewer or not note:
            raise ValueError("Resolved items require reviewer and note")
    
    # Update exception
    exception.status = new_status
    exception.reviewer = reviewer
    exception.note = note
    exception.resolved_date = date.today()
    
    # Calculate age
    exception.age_days = business_days_between(exception.opened_date, date.today())
    
    # Log audit event
    log_event("STATUS_TRANSITION", exception)
```

### Business Days Calculation

```python
def business_days_between(start, end):
    """Count weekdays between two dates."""
    days = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday=0, Friday=4
            days += 1
    return days
```

---

## Export System

### Excel Export

**CSV Format:**

```
exception_id,mark_date,book,instrument,asset_class,fv_level,check_name,severity,mark,reference_price,deviation_bps,mv_impact_usd,suspected_cause,draft_commentary,status
```

**XLSX Format:**

- Sheet: "Review"
- Table: "ExceptionReview"
- Conditional formatting: CRITICAL (red), BREACH (orange), WARN (yellow)
- Freeze panes at row 2
- Auto-filter enabled

### Power BI Export

**Star Schema:**

```
dim_date (date, year, month, week, is_business_day)
dim_instrument (instrument_id, ticker, name, asset_class, fv_level, currency)
dim_book (book)
dim_severity (severity, sort_order)
dim_status (status, sort_order, is_open)

fact_marks (date, position_id, mark, reference_price, deviation_bps, mv_usd)
fact_exceptions (exception_id, date, position_id, check_name, severity, status, deviation_bps, mv_impact_usd, opened_date, resolved_date, age_days, is_simulated)
fact_backtest (fault_type, injected, detected, recall)
```

**Relationships:**

- dim_date 1 → * fact_marks
- dim_date 1 → * fact_exceptions
- dim_instrument 1 → * fact_marks
- dim_instrument 1 → * fact_exceptions
- dim_severity 1 → * fact_exceptions
- dim_status 1 → * fact_exceptions

---

## Design Decisions

### 1. SQLite for Storage

**Decision:** Use SQLite instead of PostgreSQL/MySQL

**Rationale:**
- Zero configuration (no server setup)
- Portable (single file)
- Sufficient for demonstration (millions of rows)
- Easy to backup and share

**Trade-offs:**
- Limited concurrent writes (not an issue for single-user demo)
- No advanced features (partitioning, replication)

### 2. Deterministic Exception IDs

**Decision:** Use `sha256(mark_date|position_id|check_name)[:32]`

**Rationale:**
- Idempotent: re-running validation produces same IDs
- Enables upserts without duplicates
- Traceable: ID encodes the source data

**Trade-offs:**
- Longer than sequential IDs
- Not human-readable

### 3. Separate ground_truth Table

**Decision:** Store injected faults in separate table, not in exceptions

**Rationale:**
- Clear separation: validation engine never reads ground_truth
- Backtest module has exclusive access
- Prevents accidental data leakage

**Trade-offs:**
- Requires join for backtest
- Additional storage

### 4. Template Commentary by Default

**Decision:** Use deterministic templates, LLM is optional

**Rationale:**
- Works offline (no API calls)
- Reproducible (no randomness)
- No cost (no API fees)
- Guardrails are simpler

**Trade-offs:**
- Less natural language
- No contextual understanding

### 5. Parquet for Data Cache

**Decision:** Cache reference data as Parquet files

**Rationale:**
- Columnar format (fast queries)
- Compressed (small files)
- Type-safe (schema enforcement)
- Compatible with pandas/polars

**Trade-offs:**
- Binary format (not human-readable)
- Requires Parquet library

### 6. Business Days for Ageing

**Decision:** Calculate age in business days, not calendar days

**Rationale:**
- Matches real-world review timelines
- Excludes weekends
- More meaningful for SLAs

**Trade-offs:**
- More complex calculation
- Doesn't account for holidays

### 7. Star Schema for Power BI

**Decision:** Export as star schema (dimensions + facts)

**Rationale:**
- Standard pattern for BI tools
- Efficient queries (star joins)
- Easy to understand
- Supports drill-down

**Trade-offs:**
- Requires relationship setup in Power BI
- More files than single table

---

## Future Enhancements

### Potential Improvements

1. **Real-time validation**: Intraday marks and references
2. **Multi-currency aggregation**: Portfolio-level MV impact
3. **Machine learning**: Anomaly detection for complex patterns
4. **API layer**: REST API for integration with other systems
5. **Web UI**: Browser-based review interface
6. **Alerting**: Email/Slack notifications for critical exceptions
7. **Advanced backtest**: Time-series analysis, fault correlation
8. **Regulatory reporting**: Automated filing generation

### Not Planned

- Real trading integration
- Production deployment
- Regulatory certification
- Multi-tenant support

---

## Questions?

For technical questions about the design, please open an issue on GitHub.
