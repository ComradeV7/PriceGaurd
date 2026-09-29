-- PriceGuard SQLite schema (Section 4.6)
-- Migration-free versioning: bump schema_version when changing tables.

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_ts  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS instruments (
    instrument_id   TEXT PRIMARY KEY,
    ticker          TEXT NOT NULL,
    name            TEXT NOT NULL,
    asset_class     TEXT NOT NULL,
    currency        TEXT NOT NULL,
    fv_level        INTEGER NOT NULL,
    ref_source      TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS positions (
    position_id     TEXT PRIMARY KEY,
    instrument_id   TEXT NOT NULL REFERENCES instruments(instrument_id),
    book            TEXT NOT NULL,
    quantity        REAL NOT NULL,
    currency        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reference_prices (
    instrument_id   TEXT NOT NULL REFERENCES instruments(instrument_id),
    price_date      TEXT NOT NULL,
    price           REAL NOT NULL,
    source          TEXT NOT NULL,
    PRIMARY KEY (instrument_id, price_date, source)
);

CREATE TABLE IF NOT EXISTS internal_marks (
    position_id     TEXT NOT NULL REFERENCES positions(position_id),
    mark_date       TEXT NOT NULL,
    mark            REAL,
    mark_currency   TEXT NOT NULL,
    PRIMARY KEY (position_id, mark_date)
);

-- Read ONLY by the backtest module. The validation engine must never
-- import or query this table.
CREATE TABLE IF NOT EXISTS ground_truth (
    position_id         TEXT NOT NULL REFERENCES positions(position_id),
    mark_date           TEXT NOT NULL,
    fault_type          TEXT NOT NULL,
    fault_params_json   TEXT NOT NULL,
    PRIMARY KEY (position_id, mark_date)
);

-- Level 3 model values and bands (no independent reference price).
CREATE TABLE IF NOT EXISTS l3_models (
    instrument_id   TEXT PRIMARY KEY REFERENCES instruments(instrument_id),
    model_value     REAL NOT NULL,
    band_min        REAL NOT NULL,
    band_max        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS validation_runs (
    run_id          TEXT PRIMARY KEY,
    run_ts          TEXT NOT NULL,
    mark_date       TEXT NOT NULL,
    config_hash     TEXT NOT NULL,
    n_positions     INTEGER NOT NULL,
    n_exceptions    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS exceptions (
    exception_id    TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES validation_runs(run_id),
    position_id     TEXT NOT NULL REFERENCES positions(position_id),
    mark_date       TEXT NOT NULL,
    check_name      TEXT NOT NULL,
    severity        TEXT NOT NULL,
    mark            REAL,
    reference_price REAL,
    deviation_bps   REAL,
    mv_impact_usd   REAL,
    suspected_cause TEXT,
    status          TEXT NOT NULL DEFAULT 'OPEN',
    opened_date     TEXT NOT NULL,
    resolved_date   TEXT,
    age_days        INTEGER NOT NULL DEFAULT 0,
    assigned_to     TEXT,
    resolution_note TEXT,
    is_primary      INTEGER NOT NULL DEFAULT 1,
    is_material     INTEGER NOT NULL DEFAULT 0,
    is_simulated    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS commentary (
    exception_id    TEXT NOT NULL REFERENCES exceptions(exception_id),
    draft_text      TEXT NOT NULL,
    provider        TEXT NOT NULL,
    model_name      TEXT,
    prompt_hash     TEXT,
    created_ts      TEXT NOT NULL,
    facts_json      TEXT NOT NULL,
    guardrail_passed INTEGER NOT NULL DEFAULT 1,
    review_state    TEXT NOT NULL DEFAULT 'DRAFT',
    reviewer        TEXT,
    reviewed_ts     TEXT,
    final_text      TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    event_ts    TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    entity      TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    before_json TEXT,
    after_json  TEXT
);

CREATE INDEX IF NOT EXISTS idx_exceptions_mark_date ON exceptions(mark_date);
CREATE INDEX IF NOT EXISTS idx_exceptions_status ON exceptions(status);
CREATE INDEX IF NOT EXISTS idx_marks_position ON internal_marks(position_id, mark_date);
CREATE INDEX IF NOT EXISTS idx_reference_prices_date ON reference_prices(price_date);
