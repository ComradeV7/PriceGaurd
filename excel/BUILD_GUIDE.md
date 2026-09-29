# Excel Review Workbook Build Guide

This guide walks you through creating the PriceGuard Excel review workbook
from scratch. The workbook uses VBA macros to load, format, review, and
export exception data.

> **Important:** This code cannot be executed in the sandbox environment.
> You must test it in Microsoft Excel on Windows or Mac.

## Prerequisites

- Microsoft Excel 2016 or later (Windows or Mac)
- Macro-enabled workbook support (.xlsm)
- A `daily_exceptions_YYYYMMDD.csv` file exported by the Python pipeline

## Step 1: Create a Blank Macro-Enabled Workbook

1. Open Excel
2. Click **File > New > Blank workbook**
3. Click **File > Save As**
4. Choose a location (e.g., `priceguard/excel/`)
5. Set file name to `ExceptionReview.xlsm`
6. Set **Save as type** to **Excel Macro-Enabled Workbook (*.xlsm)**
7. Click **Save**

## Step 2: Import the VBA Module

1. Press **Alt + F11** to open the VBA Editor
2. In the Project Explorer (left panel), right-click on **VBAProject (ExceptionReview.xlsm)**
3. Select **Insert > Module**
4. A new module (Module1) appears
5. In the Properties window (F4), change **(Name)** to `ExceptionReview`
6. Open the file `ExceptionReview.bas` in a text editor
7. Copy all contents (Ctrl+A, Ctrl+C)
8. Paste into the VBA Editor (Ctrl+V)
9. Close the VBA Editor (Alt+Q)

## Step 3: Enable Macros

1. Click **File > Options > Trust Center**
2. Click **Trust Center Settings**
3. Select **Macro Settings**
4. Choose **Disable all macros with notification**
5. Click **OK**
6. Close and reopen the workbook
7. When prompted, click **Enable Content**

> **Security Note:** Only enable macros from trusted sources. The
> ExceptionReview.bas file in this repository is safe to review before
> enabling.

## Step 4: Create the Control Sheet

1. Rename Sheet1 to **Control**
2. Add the following buttons (Developer tab > Insert > Button):

| Button | Macro to Assign |
|--------|----------------|
| Load Exceptions | LoadExceptions |
| Format Review Sheet | FormatReviewSheet |
| Apply Severity Formatting | ApplySeverityFormatting |
| Add Review Controls | AddReviewControls |
| Build Summary Sheet | BuildSummarySheet |
| Validate Sign-Off | ValidateSignOff |
| Export Reviewed CSV | ExportReviewedCSV |

3. Format each button with a descriptive label
4. Save the workbook

## Step 5: Manual Test Checklist

Use this checklist to verify the workbook works correctly with exported data:

### Test 1: Load Exceptions

- [ ] Click **Load Exceptions**
- [ ] Select a `daily_exceptions_YYYYMMDD.csv` file
- [ ] Verify data appears in the **Review** sheet
- [ ] Verify a table named `ExceptionReview` is created
- [ ] Check that column headers match the CSV

### Test 2: Format Review Sheet

- [ ] Click **Format Review Sheet**
- [ ] Verify freeze panes at row 2
- [ ] Verify column widths are appropriate
- [ ] Verify number formats (decimals for prices, no decimals for counts)
- [ ] Verify autofilter is enabled

### Test 3: Apply Severity Formatting

- [ ] Click **Apply Severity Formatting**
- [ ] Verify CRITICAL rows have red background
- [ ] Verify BREACH rows have orange background
- [ ] Verify WARN rows have yellow background
- [ ] Verify PASS rows have green background

### Test 4: Add Review Controls

- [ ] Click **Add Review Controls**
- [ ] Verify new columns appear: Reviewer, Reviewed Date, Comment, Sign-off
- [ ] Click a cell in the Status column
- [ ] Verify a dropdown appears with: OPEN, UNDER_REVIEW, RESOLVED, ADJUSTED, ESCALATED
- [ ] Click a cell in the Sign-off column
- [ ] Verify a dropdown appears with: Yes, No

### Test 5: Build Summary Sheet

- [ ] Click **Build Summary Sheet**
- [ ] Verify a **Summary** sheet is created
- [ ] Verify counts by severity (CRITICAL, BREACH, WARN, PASS)
- [ ] Verify counts by status (OPEN, UNDER_REVIEW, RESOLVED, ADJUSTED, ESCALATED)
- [ ] Verify total absolute MV impact is calculated
- [ ] Verify total exceptions count matches the Review table

### Test 6: Review Workflow

- [ ] In the Review sheet, change a row's Status to **RESOLVED**
- [ ] Fill in Reviewer, Reviewed Date, and Comment
- [ ] Set Sign-off to **Yes**
- [ ] Click **Validate Sign-Off**
- [ ] Verify no error message appears
- [ ] Change another row's Status to **RESOLVED** but leave fields blank
- [ ] Click **Validate Sign-Off**
- [ ] Verify the row is highlighted in red with an error message

### Test 7: Export Reviewed CSV

- [ ] Click **Export Reviewed CSV**
- [ ] Verify a file is created in the TEMP directory
- [ ] Open the exported CSV
- [ ] Verify all columns are present
- [ ] Verify reviewed data is included

### Test 8: Macro Log

- [ ] Open the **MacroLog** sheet
- [ ] Verify each macro run is logged with timestamp, user, macro name, and row count

## Troubleshooting

### "Compile error: User-defined type not defined"

Ensure you're using Excel 2016 or later. The code uses modern Excel objects.

### "Run-time error 9: Subscript out of range"

The Review sheet doesn't exist. Run **Load Exceptions** first.

### "Run-time error 1004: Application-defined or object-defined error"

The table name `ExceptionReview` already exists. Delete the existing table
or rename it before loading new data.

### Macros don't run

- Ensure macros are enabled (File > Options > Trust Center)
- Ensure the file is saved as .xlsm (not .xlsx)
- Check that the VBA module is named `ExceptionReview`

## Data Sources and Terms

The CSV files loaded by this workbook are generated by the PriceGuard Python
pipeline using public market data from:

- **Yahoo Finance** (via yfinance): Equity and ETF prices
- **FRED** (Federal Reserve Economic Data): Treasury yields
- **Frankfurter API** (ECB): FX reference rates
- **Stooq**: Alternative equity/ETF prices

All positions and internal marks are **synthetic**. This workbook is for
demonstration and learning purposes only.

## Next Steps

After reviewing exceptions in Excel:

1. Export the reviewed CSV using **Export Reviewed CSV**
2. Copy the file to the project root as `reviewed_YYYYMMDD.csv`
3. Run `uv run python -m priceguard.cli review --action ingest-csv --csv-path reviewed_YYYYMMDD.csv --reviewer "Your Name"`
4. The Python pipeline will update exception statuses and audit the changes
