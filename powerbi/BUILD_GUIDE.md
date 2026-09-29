# Power BI Build Guide

This guide walks you through creating the PriceGuard Power BI report from
the exported CSV files.

> **Important:** This code cannot be executed in the sandbox environment.
> You must test it in Power BI Desktop on Windows.

## Prerequisites

- Power BI Desktop (latest version)
- CSV files exported by the Python pipeline in `exports/powerbi/`:
  - dim_date.csv
  - dim_instrument.csv
  - dim_book.csv
  - dim_severity.csv
  - dim_status.csv
  - fact_marks.csv
  - fact_exceptions.csv
  - fact_backtest.csv
  - schema.json

## Step 1: Generate Export Files

Run the Python pipeline to generate the Power BI CSV files:

```bash
uv run python -m priceguard.cli run-all --offline
```

This creates all CSV files in `exports/powerbi/`.

## Step 2: Create a New Power BI Report

1. Open Power BI Desktop
2. Click **Blank report**
3. Save the report as `PriceGuard.pbix` in the `powerbi/` directory

## Step 3: Load Data with Power Query

### Set the Folder Path Parameter

1. Click **Transform data** to open Power Query Editor
2. Click **Manage Parameters** > **New Parameter**
3. Set:
   - Name: `FolderPath`
   - Type: Text
   - Current Value: Full path to `exports/powerbi/` (e.g., `D:\Dev\PriceGaurd\exports\powerbi`)
4. Click **OK**

### Load Each Query

For each dimension and fact table:

1. Click **New Source** > **Blank Query**
2. Click **Advanced Editor**
3. Copy the contents of the corresponding `.pq` file from `powerbi/queries/`:
   - dim_date.pq
   - dim_instrument.pq
   - dim_book.pq
   - dim_severity.pq
   - dim_status.pq
   - fact_marks.pq
   - fact_exceptions.pq
   - fact_backtest.pq
4. Paste into the Advanced Editor
5. Click **Done**
6. Rename the query to match the table name (e.g., "dim_date")
7. Repeat for all 8 queries

### Close and Apply

1. Click **Close & Apply** in the Home tab
2. Wait for data to load

## Step 4: Create Relationships

In the Model view, create the following relationships:

### fact_marks Relationships

1. **dim_date → fact_marks**
   - From: dim_date[date]
   - To: fact_marks[date]
   - Cardinality: One to many (1:*)
   - Cross-filter direction: Single

2. **dim_instrument → fact_marks**
   - From: dim_instrument[instrument_id]
   - To: fact_marks[position_id] (Note: position_id maps to instrument_id)
   - Cardinality: One to many (1:*)
   - Cross-filter direction: Single

3. **dim_book → fact_marks**
   - From: dim_book[book]
   - To: fact_marks[book] (Note: requires a book column in fact_marks or a join through positions)
   - Cardinality: One to many (1:*)
   - Cross-filter direction: Single

### fact_exceptions Relationships

1. **dim_date → fact_exceptions**
   - From: dim_date[date]
   - To: fact_exceptions[date]
   - Cardinality: One to many (1:*)
   - Cross-filter direction: Single

2. **dim_instrument → fact_exceptions**
   - From: dim_instrument[instrument_id]
   - To: fact_exceptions[position_id]
   - Cardinality: One to many (1:*)
   - Cross-filter direction: Single

3. **dim_book → fact_exceptions**
   - From: dim_book[book]
   - To: fact_exceptions[book] (Note: requires a book column or join)
   - Cardinality: One to many (1:*)
   - Cross-filter direction: Single

4. **dim_severity → fact_exceptions**
   - From: dim_severity[severity]
   - To: fact_exceptions[severity]
   - Cardinality: One to many (1:*)
   - Cross-filter direction: Single

5. **dim_status → fact_exceptions**
   - From: dim_status[status]
   - To: fact_exceptions[status]
   - Cardinality: One to many (1:*)
   - Cross-filter direction: Single

**Note:** If fact_marks and fact_exceptions don't have book columns, you may
need to create a position dimension or use many-to-many relationships through
a position table.

## Step 5: Add DAX Measures

1. In the Model view, right-click on **fact_exceptions**
2. Select **New measure**
3. Copy each measure from `powerbi/measures.dax` and paste it into the formula bar
4. Press **Enter** to save each measure
5. Repeat for all measures

Key measures to add:

- Total Exceptions
- Open Exceptions
- Breach Rate
- Critical Count
- Absolute MV Impact
- Average Age (Open)
- Items Older Than 5 Days
- Resolution Rate
- Exceptions vs Prior Week
- Top Check by Count
- Coverage
- Overall Recall

## Step 6: Mark dim_date as Date Table

1. In the Fields pane, right-click **dim_date**
2. Select **Mark as date table**
3. In the dialog, set **Date column** to `dim_date[date]`
4. Click **OK**

## Step 7: Build Report Pages

### Page 1: Overview

1. Click **+** to add a new page
2. Rename to "Overview"
3. Add visuals:
   - **Card**: Total Exceptions
   - **Card**: Open Exceptions (add conditional formatting: red if > 10)
   - **Card**: Critical Count (red background)
   - **Card**: Breach Rate (format as %)
   - **Card**: Absolute MV Impact (format as $)
   - **Line chart**: Exceptions over time (X: dim_date[date], Y: Total Exceptions, Legend: dim_severity[severity])
   - **Donut chart**: Severity breakdown (Legend: dim_severity[severity], Values: Total Exceptions)
   - **Bar chart**: Asset class distribution (X: dim_instrument[asset_class], Y: Total Exceptions)

### Page 2: Asset Class Drill-Down

1. Add a new page named "Asset Class Drill-Down"
2. Add visuals:
   - **Matrix**: Asset class × check (Rows: dim_instrument[asset_class], Columns: fact_exceptions[check_name], Values: Total Exceptions)
   - **Histogram**: Deviation distribution (X: fact_exceptions[deviation_bps] with bins, Y: Total Exceptions)
   - **Bar chart**: Top 10 instruments by impact (Y: dim_instrument[ticker], X: Absolute MV Impact, filter top 10)
   - **Stacked bar**: FV level breakdown (X: dim_instrument[fv_level], Y: Total Exceptions, Legend: dim_severity[severity])

### Page 3: Workflow and Ageing

1. Add a new page named "Workflow and Ageing"
2. Add visuals:
   - **Funnel chart**: Status funnel (Values: dim_status[status], Metric: Total Exceptions)
   - **Bar chart**: Ageing buckets (X: Age buckets, Y: Total Exceptions, filter: dim_status[is_open] = TRUE)
   - **Table**: Open items (columns: exception_id, date, ticker, severity, age_days, status, filter: is_open = TRUE, conditional formatting: age_days > 5 = red)
   - **Gauge**: Resolution rate (Value: Resolution Rate, Min: 0, Max: 1, Target: 0.8)
   - **Pie chart**: Simulated vs real (Legend: "Simulated"/"Real", Values: Simulated Exceptions, Real Exceptions)

### Page 4: Control Effectiveness (Backtest)

1. Add a new page named "Control Effectiveness"
2. Add visuals:
   - **Card**: Overall Recall (format as %)
   - **Bar chart**: Recall by fault type (X: fact_backtest[fault_type], Y: fact_backtest[recall])
   - **Clustered bar**: Injected vs detected (X: fact_backtest[fault_type], Y: fact_backtest[injected] and fact_backtest[detected])
   - **Table**: Detection lag (columns: fault_type, avg_lag_days, filter: fault_type IN {"STALE", "DRIFT"})
   - **Text box**: Disclaimer "Based on synthetic injected faults. Results reflect control design on synthetic data, not real-world performance."

## Step 8: Add Slicers

On each page, add slicers for:

- **Date range**: dim_date[date] (between slicer)
- **Asset class**: dim_instrument[asset_class] (dropdown)
- **Book**: dim_book[book] (dropdown)
- **Severity**: dim_severity[severity] (dropdown)

## Step 9: Apply Conditional Formatting

Apply the conditional formatting rules from MODEL.md:

1. Select a visual
2. In the Format pane, expand **Data colors** or **Cell elements**
3. Click **fx** to add conditional formatting
4. Set the rule (e.g., if severity = "CRITICAL" then red)

## Step 10: Export to PDF

1. Click **File** > **Export** > **PDF**
2. Save as `powerbi/report.pdf`
3. This creates a static snapshot of all pages

## Troubleshooting

### "The key doesn't match any rows"

The relationships are incorrect. Check that:
- fact_marks[date] matches dim_date[date] format (YYYY-MM-DD)
- fact_exceptions[position_id] exists in dim_instrument[instrument_id]
- All foreign keys have matching primary keys

### "Cannot load data"

Check that:
- The FolderPath parameter points to the correct directory
- All CSV files exist in that directory
- CSV files have the correct column names and types

### Measures show blank

Check that:
- Measures are created on the correct fact table
- Relationships are active (not inactive)
- Filter context is not excluding all rows

### Date intelligence doesn't work

Ensure dim_date is marked as a date table:
1. Right-click dim_date
2. Select **Mark as date table**
3. Set date column to dim_date[date]

## Next Steps

After building the report:

1. Save the .pbix file
2. Export to PDF for documentation
3. Take screenshots of each page for the README
4. Commit the .pbix and PDF to the repository (optional)

## Data Sources and Terms

The CSV files loaded by this report are generated by the PriceGuard Python
pipeline using public market data from:

- **Yahoo Finance** (via yfinance): Equity and ETF prices
- **FRED** (Federal Reserve Economic Data): Treasury yields
- **Frankfurter API** (ECB): FX reference rates
- **Stooq**: Alternative equity/ETF prices

All positions and internal marks are **synthetic**. This report is for
demonstration and learning purposes only.
