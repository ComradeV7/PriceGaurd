# Power BI Model

This document describes the star-schema model and report layout for the
PriceGuard Power BI dashboard.

## Star Schema

The model follows a classic star schema with five dimension tables and three
fact tables.

### Dimensions

| Table | Key | Description |
|-------|-----|-------------|
| dim_date | date | Calendar dates with year, month, week, business day flag |
| dim_instrument | instrument_id | Instruments with ticker, name, asset class, FV level, currency |
| dim_book | book | Trading books (Trading-A, Treasury, Banking-B) |
| dim_severity | severity | Exception severity levels (PASS, WARN, BREACH, CRITICAL) |
| dim_status | status | Exception workflow status (OPEN, UNDER_REVIEW, RESOLVED, ADJUSTED, ESCALATED) |

### Facts

| Table | Grain | Description |
|-------|-------|-------------|
| fact_marks | position_id × date | Daily marks with reference prices and deviations |
| fact_exceptions | exception_id | Validated exceptions with severity, impact, and workflow status |
| fact_backtest | fault_type | Backtest results by fault type (injected, detected, recall) |

### Relationships

All relationships are **one-to-many, single direction** from dimensions to facts:

```
dim_date 1 → * fact_marks
dim_date 1 → * fact_exceptions

dim_instrument 1 → * fact_marks (via position_id → instrument_id)
dim_instrument 1 → * fact_exceptions (via position_id → instrument_id)

dim_book 1 → * fact_marks (via position_id → book)
dim_book 1 → * fact_exceptions (via position_id → book)

dim_severity 1 → * fact_exceptions (via severity)
dim_status 1 → * fact_exceptions (via status)
```

**Note:** fact_marks does not have direct relationships to dim_severity or
dim_status because marks are not exceptions. The deviation_bps and mv_usd
columns in fact_marks are calculated fields, not exceptions.

## Report Pages

### Page 1: Overview

**Purpose:** High-level KPIs and exception trends

**Visuals:**

1. **KPI Cards** (top row)
   - Total Exceptions (card)
   - Open Exceptions (card, red if > 10)
   - Critical Count (card, red background)
   - Breach Rate (card, formatted as %)
   - Absolute MV Impact (card, formatted as $)

2. **Exceptions Trend** (line chart)
   - X-axis: dim_date[date] (continuous)
   - Y-axis: COUNTROWS(fact_exceptions)
   - Legend: dim_severity[severity]
   - Shows daily exception counts by severity

3. **Severity Breakdown** (donut chart)
   - Legend: dim_severity[severity]
   - Values: COUNTROWS(fact_exceptions)
   - Shows proportion of exceptions by severity

4. **Asset Class Distribution** (bar chart)
   - X-axis: dim_instrument[asset_class]
   - Y-axis: COUNTROWS(fact_exceptions)
   - Shows which asset classes have the most exceptions

### Page 2: Asset Class Drill-Down

**Purpose:** Deep dive into exceptions by asset class and instrument

**Visuals:**

1. **Asset Class × Check Matrix** (matrix)
   - Rows: dim_instrument[asset_class]
   - Columns: fact_exceptions[check_name]
   - Values: COUNTROWS(fact_exceptions)
   - Shows which checks trigger for each asset class

2. **Deviation Distribution** (histogram)
   - X-axis: fact_exceptions[deviation_bps] (bins: 0-50, 50-100, 100-200, 200+)
   - Y-axis: COUNTROWS(fact_exceptions)
   - Shows distribution of deviation magnitudes

3. **Top 10 Instruments by Impact** (bar chart)
   - Y-axis: dim_instrument[ticker] (top 10 by ABS(mv_impact_usd))
   - X-axis: SUM(ABS(fact_exceptions[mv_impact_usd]))
   - Sorted descending
   - Highlights instruments with largest MV impact

4. **FV Level Breakdown** (stacked bar)
   - X-axis: dim_instrument[fv_level]
   - Y-axis: COUNTROWS(fact_exceptions)
   - Legend: dim_severity[severity]
   - Shows exceptions by fair value hierarchy level

### Page 3: Workflow and Ageing

**Purpose:** Monitor exception lifecycle and ageing

**Visuals:**

1. **Status Funnel** (funnel chart)
   - Values: dim_status[status]
   - Metric: COUNTROWS(fact_exceptions)
   - Shows progression through workflow stages

2. **Ageing Buckets** (bar chart)
   - X-axis: Age buckets (0-1, 2-5, 6-10, 10+ days)
   - Y-axis: COUNTROWS(fact_exceptions)
   - Filter: dim_status[is_open] = TRUE
   - Shows how long open exceptions have been ageing

3. **Open Items Table** (table)
   - Columns: exception_id, date, dim_instrument[ticker], severity, age_days, status
   - Filter: dim_status[is_open] = TRUE
   - Conditional formatting: age_days > 5 (red background)
   - Sorted by age_days descending

4. **Resolution Rate** (gauge)
   - Value: [Resolution Rate]
   - Min: 0%, Max: 100%
   - Target: 80%
   - Shows percentage of closed exceptions that were resolved

5. **Simulated vs Real** (pie chart)
   - Legend: "Simulated" vs "Real"
   - Values: [Simulated Exceptions], [Real Exceptions]
   - Shows proportion of simulated workflow data

### Page 4: Control Effectiveness (Backtest)

**Purpose:** Evaluate detection performance against synthetic faults

**Visuals:**

1. **Overall Recall** (card)
   - Value: [Overall Recall]
   - Formatted as %
   - Shows overall detection rate

2. **Recall by Fault Type** (bar chart)
   - X-axis: fact_backtest[fault_type]
   - Y-axis: fact_backtest[recall]
   - Shows detection rate for each fault type

3. **Injected vs Detected** (clustered bar)
   - X-axis: fact_backtest[fault_type]
   - Y-axis: fact_backtest[injected], fact_backtest[detected]
   - Shows how many faults were injected vs detected

4. **Detection Lag** (table)
   - Columns: fault_type, avg_lag_days
   - Filter: fault_type IN {"STALE", "DRIFT"}
   - Shows average detection lag for time-based faults

5. **Disclaimer** (text box)
   - "Based on synthetic injected faults. Results reflect control design on
     synthetic data, not real-world performance."

## Date Table Configuration

**dim_date** must be marked as a date table:

1. Right-click dim_date in the Fields pane
2. Select **Mark as date table**
3. Set **Date column** to dim_date[date]

This enables time intelligence functions (DATESINPERIOD, SAMEPERIODLASTYEAR, etc.)

## Filters and Slicers

**Global filters** (applied to all pages):

- Date range slicer (dim_date[date])
- Asset class slicer (dim_instrument[asset_class])
- Book slicer (dim_book[book])
- Severity slicer (dim_severity[severity])

**Page-level filters:**

- Page 3 (Workflow): dim_status[is_open] = TRUE for ageing visuals
- Page 4 (Backtest): No additional filters (shows all backtest data)

## Conditional Formatting Rules

| Visual | Field | Rule | Format |
|--------|-------|------|--------|
| Open Exceptions card | Open Exceptions | > 10 | Red background |
| Critical Count card | Critical Count | > 0 | Red background |
| Open Items Table | age_days | > 5 | Red background |
| Severity Breakdown | severity | CRITICAL | Red fill |
| Severity Breakdown | severity | BREACH | Orange fill |
| Severity Breakdown | severity | WARN | Yellow fill |

## Measures Reference

All measures are defined in `measures.dax`. Key measures:

- **Total Exceptions**: COUNTROWS(fact_exceptions)
- **Open Exceptions**: Exceptions with is_open status
- **Breach Rate**: Exceptions / position-days
- **Critical Count**: Exceptions with CRITICAL severity
- **Absolute MV Impact**: SUM(ABS(mv_impact_usd))
- **Average Age (Open)**: AVERAGE(age_days) for open exceptions
- **Items Older Than 5 Days**: Open exceptions with age_days > 5
- **Resolution Rate**: Resolved / total closed exceptions
- **Exceptions vs Prior Week**: Week-over-week change %
- **Top Check by Count**: Most frequent check_name
- **Coverage**: Positions with reference / total positions
- **Overall Recall**: SUM(detected) / SUM(injected) from backtest
