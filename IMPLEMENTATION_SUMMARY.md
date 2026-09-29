# Implementation Summary

## Config Loading & Ingest Modules - Complete

### Configuration Files Implemented

**config/settings.yaml**
- seed: 42 (for reproducibility)
- base_currency: USD
- lookback_business_days: 90
- paths: data_raw, data_sample, exports, db

**config/universe.yaml** (44 instruments)
- 15 Indian equities (Level 1, yfinance .NS tickers)
- 5 US/global equities (Level 1, yfinance)
- 6 Bond ETFs (Level 1, yfinance)
- 8 FX pairs (Level 1, Frankfurter API)
- 5 Model-priced bonds (Level 2, FRED Treasury yields)
- 5 Illiquid/private instruments (Level 3, no independent quote)

**config/tolerances.yaml**
- equity_l1: warn 50 bps, breach 100 bps
- bond_etf_l1: warn 75 bps, breach 150 bps
- fx_l1: warn 25 bps, breach 50 bps
- bond_l2: warn 30 bps, breach 75 bps
- l3: band 5%, daily_move 2%
- severity: critical_multiple 5x
- stale: min_days 2, ref_move_bps 20
- drift: consecutive_days 3
- materiality: mv_threshold_usd 10000

**config/fault_injection.yaml**
- injection_rate: 0.04 (4% of position-days)
- subtle_fraction: 0.10 (10% subtle faults)
- fault_type_weights: STALE 25%, FAT_FINGER 25%, MISSING 20%, DRIFT 20%, CURRENCY_MISMATCH 10%
- fault_parameters: per-type configuration

### Pydantic Models (src/priceguard/config.py)

**Validation Rules**
- Positive thresholds (warn_bps > 0, breach_bps > 0)
- warn < breach relationship enforced
- Known asset classes: equity, bond_etf, fx, bond_l2, l3
- Known fair value levels: 1, 2, 3
- Known reference sources: yahoo, fred, fx, stooq, none
- Currency codes: 3-letter alpha
- Fault weights sum to 1.0
- Fault types in weights match parameters

**Config Hash**
- SHA256 hash of normalized YAML contents
- Deterministic across runs
- Changes when any threshold changes

### Ingest Modules

**cache.py** - Parquet cache
- Keyed by source, symbol, date range
- force_refresh flag to bypass cache
- put/get/clear methods

**yahoo.py** - Yahoo Finance
- Endpoint: yfinance library (unofficial)
- Fetches daily adjusted close prices
- Retries with backoff (max_retries=3)
- Returns: symbol, price_date, price, source

**fred.py** - FRED Treasury Yields
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv
- No API key required (optional FRED_API_KEY env var)
- Series: DGS2, DGS5, DGS10, DGS30
- Returns: symbol, price_date, price, source

**fx.py** - Foreign Exchange
- Primary: Frankfurter API (https://api.frankfurter.app)
- Fallback: yfinance FX (e.g., EURUSD=X)
- Pairs: EURUSD, GBPUSD, USDINR, USDJPY, USDCHF, AUDUSD, USDSGD, USDCAD
- Returns: symbol, price_date, price, source

**stooq.py** - Stooq CSV
- Endpoint: https://stooq.com/q/d/l/
- Graceful failure: logs warning and skips if unavailable
- Returns: symbol, price_date, price, source

### CLI Commands

**ingest**
- `--offline`: Use sample data instead of fetching
- `--force-refresh`: Bypass cache
- `--config-dir`: Configuration directory (default: config)
- Prints coverage summary: symbol, first_date, last_date, records

### Sample Data

**data/sample/** - Generated sample dataset
- 11 Yahoo symbols (equities + bond ETFs)
- 5 FX pairs
- 4 FRED series
- 90 business days ending 2024-12-31
- Deterministic generation with seed=42

### Tests

**test_config.py** (12 tests)
- Valid config loads successfully
- Invalid seed/currency/asset_class/fv_level raises error
- warn > breach raises error
- Negative threshold raises error
- Fault weights not summing to 1 raises error
- Config hash changes with threshold
- Config hash is deterministic
- Empty instruments raises error
- Real config files load successfully

**test_ingest.py** (9 tests)
- Cache put/get/force_refresh/clear
- Yahoo fetch with mocked response
- FRED fetch with mocked response
- FX fetch with mocked response
- Stooq fetch with mocked response
- Stooq no data handling
- Stooq failure graceful handling

**test_cli.py** (3 tests)
- CLI help shows all commands
- Ingest offline mode
- Placeholder commands show not implemented

### Verification

```bash
uv run ruff check .        # All checks passed!
uv run pytest -v           # 25 passed in 1.57s
uv run python -m priceguard.cli --help  # All commands listed
```

### Endpoints Used

1. **Yahoo Finance**: yfinance library (unofficial, no guaranteed availability)
2. **FRED**: https://fred.stlouisfed.org/graph/fredgraph.csv (public CSV)
3. **Frankfurter API**: https://api.frankfurter.app (ECB reference rates)
4. **Stooq**: https://stooq.com/q/d/l/ (public CSV)

### Files Created/Modified

- config/settings.yaml
- config/universe.yaml
- config/tolerances.yaml
- config/fault_injection.yaml
- src/priceguard/config.py
- src/priceguard/cli.py
- src/priceguard/ingest/cache.py
- src/priceguard/ingest/yahoo.py
- src/priceguard/ingest/fred.py
- src/priceguard/ingest/fx.py
- src/priceguard/ingest/stooq.py
- scripts/generate_sample_data.py
- data/sample/*.parquet (11 files)
- tests/unit/test_config.py
- tests/unit/test_ingest.py
- tests/unit/test_cli.py

### Next Steps

Ready for Prompt 3: Synthetic portfolio generation, internal marks, and fault injection.
