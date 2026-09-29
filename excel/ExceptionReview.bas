Attribute VB_Name = "ExceptionReview"
Option Explicit

' =============================================================================
' ExceptionReview - PriceGuard Excel review workbook macros
' =============================================================================
' This module implements the daily exception review workflow described in
' Section 7.1 of the PriceGuard specification. It loads exception data from
' CSV files exported by the Python pipeline, formats them for review, adds
' reviewer controls, builds summary statistics, validates sign-off, and
' exports reviewed data back to CSV for re-ingestion.
'
' All macros use ListObjects (Excel tables) and named ranges rather than
' fixed cell addresses, making the workbook resilient to row/column changes.
' =============================================================================

' -----------------------------------------------------------------------------
' Constants
' -----------------------------------------------------------------------------
Private Const REVIEW_SHEET As String = "Review"
Private Const SUMMARY_SHEET As String = "Summary"
Private Const CONTROL_SHEET As String = "Control"
Private Const MACRO_LOG_SHEET As String = "MacroLog"
Private Const TABLE_NAME As String = "ExceptionReview"
Private Const STATUS_LIST As String = "OPEN,UNDER_REVIEW,RESOLVED,ADJUSTED,ESCALATED"

' Column indices in the Review table (1-based)
Private Const COL_EXCEPTION_ID As Long = 1
Private Const COL_MARK_DATE As Long = 2
Private Const COL_BOOK As Long = 3
Private Const COL_INSTRUMENT As Long = 4
Private Const COL_ASSET_CLASS As Long = 5
Private Const COL_FV_LEVEL As Long = 6
Private Const COL_CHECK_NAME As Long = 7
Private Const COL_SEVERITY As Long = 8
Private Const COL_MARK As Long = 9
Private Const COL_REFERENCE_PRICE As Long = 10
Private Const COL_DEVIATION_BPS As Long = 11
Private Const COL_MV_IMPACT_USD As Long = 12
Private Const COL_SUSPECTED_CAUSE As Long = 13
Private Const COL_DRAFT_COMMENTARY As Long = 14
Private Const COL_STATUS As Long = 15
Private Const COL_REVIEWER As Long = 16
Private Const COL_REVIEWED_DATE As Long = 17
Private Const COL_COMMENT As Long = 18
Private Const COL_SIGN_OFF As Long = 19

' =============================================================================
' LoadExceptions
' =============================================================================
' Opens a file picker dialog for the user to select a daily_exceptions CSV file,
' then imports it into the Review sheet as a formatted Excel table.
' =============================================================================
Public Sub LoadExceptions()
    On Error GoTo ErrorHandler
    
    Dim fd As FileDialog
    Dim filePath As String
    Dim ws As Worksheet
    Dim wb As Workbook
    
    Set fd = Application.FileDialog(msoFileDialogFilePicker)
    fd.Title = "Select daily exceptions CSV"
    fd.Filters.Clear
    fd.Filters.Add "CSV Files", "*.csv"
    fd.AllowMultiSelect = False
    
    If fd.Show <> -1 Then
        MsgBox "No file selected.", vbInformation, "LoadExceptions"
        Exit Sub
    End If
    
    filePath = fd.SelectedItems(1)
    
    ' Check if Review sheet exists, create if not
    On Error Resume Next
    Set ws = ThisWorkbook.Sheets(REVIEW_SHEET)
    On Error GoTo ErrorHandler
    
    If ws Is Nothing Then
        Set ws = ThisWorkbook.Sheets.Add(After:=ThisWorkbook.Sheets(ThisWorkbook.Sheets.Count))
        ws.Name = REVIEW_SHEET
    Else
        ws.Cells.Clear
    End If
    
    ' Import CSV using QueryTable
    Application.ScreenUpdating = False
    
    With ws.QueryTables.Add("TEXT;" & filePath, ws.Range("A1"))
        .TextFileParseType = xlDelimited
        .TextFileCommaDelimiter = True
        .TextFileColumnDataTypes = Array(2, 2, 2, 2, 2, 1, 2, 2, 1, 1, 1, 1, 2, 2, 2)
        .TextFileTextQualifier = xlTextQualifierDoubleQuote
        .TextFileConsecutiveDelimiter = False
        .Refresh
    End With
    
    ' Convert to table
    Dim lastRow As Long
    Dim lastCol As Long
    lastRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
    lastCol = ws.Cells(1, ws.Columns.Count).End(xlToLeft).Column
    
    If lastRow > 1 Then
        Dim tblRange As Range
        Set tblRange = ws.Range(ws.Cells(1, 1), ws.Cells(lastRow, lastCol))
        
        ' Remove existing table if present
        Dim tbl As ListObject
        For Each tbl In ws.ListObjects
            If tbl.Name = TABLE_NAME Then
                tbl.Unlist
                Exit For
            End If
        Next tbl
        
        Set tbl = ws.ListObjects.Add(xlSrcRange, tblRange, , xlYes)
        tbl.Name = TABLE_NAME
        tbl.TableStyle = "TableStyleMedium2"
    End If
    
    Application.ScreenUpdating = True
    
    ' Format the sheet
    FormatReviewSheet
    
    ' Log the macro run
    LogMacroRun "LoadExceptions", lastRow - 1
    
    MsgBox "Loaded " & (lastRow - 1) & " exceptions from:" & vbCrLf & filePath, _
           vbInformation, "LoadExceptions"
    
    Exit Sub
    
ErrorHandler:
    Application.ScreenUpdating = True
    MsgBox "Error loading exceptions: " & Err.Description, vbCritical, "LoadExceptions"
End Sub

' =============================================================================
' FormatReviewSheet
' =============================================================================
' Applies number formats, freeze panes, column widths, and autofilter to the
' Review sheet. Uses the ExceptionReview table for column references.
' =============================================================================
Public Sub FormatReviewSheet()
    On Error GoTo ErrorHandler
    
    Dim ws As Worksheet
    Dim tbl As ListObject
    
    Set ws = ThisWorkbook.Sheets(REVIEW_SHEET)
    
    ' Find the table
    On Error Resume Next
    Set tbl = ws.ListObjects(TABLE_NAME)
    On Error GoTo ErrorHandler
    
    If tbl Is Nothing Then
        MsgBox "No ExceptionReview table found on Review sheet.", vbExclamation, "FormatReviewSheet"
        Exit Sub
    End If
    
    Application.ScreenUpdating = False
    
    ' Freeze panes at row 2
    ws.Activate
    ws.Range("A2").Select
    ActiveWindow.FreezePanes = True
    
    ' Set column widths
    With tbl
        .ListColumns(COL_EXCEPTION_ID).ColumnWidth = 20
        .ListColumns(COL_MARK_DATE).ColumnWidth = 12
        .ListColumns(COL_BOOK).ColumnWidth = 12
        .ListColumns(COL_INSTRUMENT).ColumnWidth = 15
        .ListColumns(COL_ASSET_CLASS).ColumnWidth = 12
        .ListColumns(COL_FV_LEVEL).ColumnWidth = 8
        .ListColumns(COL_CHECK_NAME).ColumnWidth = 18
        .ListColumns(COL_SEVERITY).ColumnWidth = 10
        .ListColumns(COL_MARK).ColumnWidth = 14
        .ListColumns(COL_REFERENCE_PRICE).ColumnWidth = 14
        .ListColumns(COL_DEVIATION_BPS).ColumnWidth = 14
        .ListColumns(COL_MV_IMPACT_USD).ColumnWidth = 16
        .ListColumns(COL_SUSPECTED_CAUSE).ColumnWidth = 20
        .ListColumns(COL_DRAFT_COMMENTARY).ColumnWidth = 40
        .ListColumns(COL_STATUS).ColumnWidth = 14
    End With
    
    ' Number formats
    With tbl
        .ListColumns(COL_MARK).DataBodyRange.NumberFormat = "#,##0.0000"
        .ListColumns(COL_REFERENCE_PRICE).DataBodyRange.NumberFormat = "#,##0.0000"
        .ListColumns(COL_DEVIATION_BPS).DataBodyRange.NumberFormat = "#,##0.00"
        .ListColumns(COL_MV_IMPACT_USD).DataBodyRange.NumberFormat = "#,##0.00"
    End With
    
    ' Apply severity formatting
    ApplySeverityFormatting
    
    ' Add review controls
    AddReviewControls
    
    Application.ScreenUpdating = True
    
    LogMacroRun "FormatReviewSheet", tbl.ListRows.Count
    
    Exit Sub
    
ErrorHandler:
    Application.ScreenUpdating = True
    MsgBox "Error formatting sheet: " & Err.Description, vbCritical, "FormatReviewSheet"
End Sub

' =============================================================================
' ApplySeverityFormatting
' =============================================================================
' Applies conditional formatting to the severity column:
' - CRITICAL: Red background
' - BREACH: Orange background
' - WARN: Yellow background
' - PASS: Green background
' =============================================================================
Public Sub ApplySeverityFormatting()
    On Error GoTo ErrorHandler
    
    Dim ws As Worksheet
    Dim tbl As ListObject
    Dim severityRange As Range
    
    Set ws = ThisWorkbook.Sheets(REVIEW_SHEET)
    
    On Error Resume Next
    Set tbl = ws.ListObjects(TABLE_NAME)
    On Error GoTo ErrorHandler
    
    If tbl Is Nothing Then
        MsgBox "No ExceptionReview table found.", vbExclamation, "ApplySeverityFormatting"
        Exit Sub
    End If
    
    Set severityRange = tbl.ListColumns(COL_SEVERITY).DataBodyRange
    
    ' Clear existing conditional formatting
    severityRange.FormatConditions.Delete
    
    ' CRITICAL - Red
    With severityRange.FormatConditions.Add(xlCellValue, xlEqual, "CRITICAL")
        .Interior.Color = RGB(255, 100, 100)
        .Font.Bold = True
    End With
    
    ' BREACH - Orange
    With severityRange.FormatConditions.Add(xlCellValue, xlEqual, "BREACH")
        .Interior.Color = RGB(255, 180, 100)
        .Font.Bold = True
    End With
    
    ' WARN - Yellow
    With severityRange.FormatConditions.Add(xlCellValue, xlEqual, "WARN")
        .Interior.Color = RGB(255, 255, 150)
    End With
    
    ' PASS - Green
    With severityRange.FormatConditions.Add(xlCellValue, xlEqual, "PASS")
        .Interior.Color = RGB(150, 255, 150)
    End With
    
    LogMacroRun "ApplySeverityFormatting", severityRange.Rows.Count
    
    Exit Sub
    
ErrorHandler:
    MsgBox "Error applying severity formatting: " & Err.Description, vbCritical, "ApplySeverityFormatting"
End Sub

' =============================================================================
' AddReviewControls
' =============================================================================
' Adds reviewer columns (Reviewer, Reviewed Date, Comment, Sign-off) to the
' right of the table and adds data validation dropdown for Status column.
' =============================================================================
Public Sub AddReviewControls()
    On Error GoTo ErrorHandler
    
    Dim ws As Worksheet
    Dim tbl As ListObject
    Dim lastCol As Long
    Dim statusRange As Range
    
    Set ws = ThisWorkbook.Sheets(REVIEW_SHEET)
    
    On Error Resume Next
    Set tbl = ws.ListObjects(TABLE_NAME)
    On Error GoTo ErrorHandler
    
    If tbl Is Nothing Then
        MsgBox "No ExceptionReview table found.", vbExclamation, "AddReviewControls"
        Exit Sub
    End If
    
    ' Check if review columns already exist
    If tbl.ListColumns.Count >= COL_SIGN_OFF Then
        ' Columns already exist, just add validation
        GoTo AddValidation
    End If
    
    ' Add headers for review columns
    lastCol = tbl.Range.Columns.Count
    
    With ws
        .Cells(1, lastCol + 1).Value = "Reviewer"
        .Cells(1, lastCol + 2).Value = "Reviewed Date"
        .Cells(1, lastCol + 3).Value = "Comment"
        .Cells(1, lastCol + 4).Value = "Sign-off"
    End With
    
    ' Resize table to include new columns
    Dim newRange As Range
    Set newRange = ws.Range(ws.Cells(1, 1), ws.Cells(tbl.Range.Rows.Count, lastCol + 4))
    tbl.Resize newRange
    
    ' Format new columns
    With tbl
        .ListColumns(COL_REVIEWER).ColumnWidth = 15
        .ListColumns(COL_REVIEWED_DATE).ColumnWidth = 14
        .ListColumns(COL_COMMENT).ColumnWidth = 30
        .ListColumns(COL_SIGN_OFF).ColumnWidth = 10
    End With
    
AddValidation:
    ' Add data validation to Status column
    Set statusRange = tbl.ListColumns(COL_STATUS).DataBodyRange
    
    With statusRange.Validation
        .Delete
        .Add Type:=xlValidateList, AlertStyle:=xlValidAlertStop, _
             Operator:=xlBetween, Formula1:=STATUS_LIST
        .IgnoreBlank = True
        .InCellDropdown = True
        .ShowInput = True
        .ShowError = True
    End With
    
    ' Add data validation to Sign-off column (Yes/No)
    Dim signOffRange As Range
    Set signOffRange = tbl.ListColumns(COL_SIGN_OFF).DataBodyRange
    
    With signOffRange.Validation
        .Delete
        .Add Type:=xlValidateList, AlertStyle:=xlValidAlertStop, _
             Operator:=xlBetween, Formula1:="Yes,No"
        .IgnoreBlank = True
        .InCellDropdown = True
    End With
    
    LogMacroRun "AddReviewControls", tbl.ListRows.Count
    
    Exit Sub
    
ErrorHandler:
    MsgBox "Error adding review controls: " & Err.Description, vbCritical, "AddReviewControls"
End Sub

' =============================================================================
' BuildSummarySheet
' =============================================================================
' Creates or updates the Summary sheet with counts by severity, asset class,
' and status, plus total absolute MV impact using formulas.
' =============================================================================
Public Sub BuildSummarySheet()
    On Error GoTo ErrorHandler
    
    Dim wsSummary As Worksheet
    Dim wsReview As Worksheet
    Dim tbl As ListObject
    Dim severityRange As Range
    Dim assetRange As Range
    Dim statusRange As Range
    Dim impactRange As Range
    
    Set wsReview = ThisWorkbook.Sheets(REVIEW_SHEET)
    
    On Error Resume Next
    Set tbl = wsReview.ListObjects(TABLE_NAME)
    On Error GoTo ErrorHandler
    
    If tbl Is Nothing Then
        MsgBox "No ExceptionReview table found.", vbExclamation, "BuildSummarySheet"
        Exit Sub
    End If
    
    ' Create or clear Summary sheet
    On Error Resume Next
    Set wsSummary = ThisWorkbook.Sheets(SUMMARY_SHEET)
    On Error GoTo ErrorHandler
    
    If wsSummary Is Nothing Then
        Set wsSummary = ThisWorkbook.Sheets.Add(After:=wsReview)
        wsSummary.Name = SUMMARY_SHEET
    Else
        wsSummary.Cells.Clear
    End If
    
    ' Set up ranges
    Set severityRange = tbl.ListColumns(COL_SEVERITY).DataBodyRange
    Set assetRange = tbl.ListColumns(COL_ASSET_CLASS).DataBodyRange
    Set statusRange = tbl.ListColumns(COL_STATUS).DataBodyRange
    Set impactRange = tbl.ListColumns(COL_MV_IMPACT_USD).DataBodyRange
    
    ' Build summary with formulas
    With wsSummary
        .Range("A1").Value = "PriceGuard Exception Summary"
        .Range("A1").Font.Bold = True
        .Range("A1").Font.Size = 14
        
        ' Severity counts
        .Range("A3").Value = "By Severity"
        .Range("A3").Font.Bold = True
        .Range("A4").Value = "CRITICAL"
        .Range("A5").Value = "BREACH"
        .Range("A6").Value = "WARN"
        .Range("A7").Value = "PASS"
        .Range("B4").Formula = "=COUNTIF(" & severityRange.Address(True, True, xlA1, True) & ",""CRITICAL"")"
        .Range("B5").Formula = "=COUNTIF(" & severityRange.Address(True, True, xlA1, True) & ",""BREACH"")"
        .Range("B6").Formula = "=COUNTIF(" & severityRange.Address(True, True, xlA1, True) & ",""WARN"")"
        .Range("B7").Formula = "=COUNTIF(" & severityRange.Address(True, True, xlA1, True) & ",""PASS"")"
        
        ' Status counts
        .Range("D3").Value = "By Status"
        .Range("D3").Font.Bold = True
        .Range("D4").Value = "OPEN"
        .Range("D5").Value = "UNDER_REVIEW"
        .Range("D6").Value = "RESOLVED"
        .Range("D7").Value = "ADJUSTED"
        .Range("D8").Value = "ESCALATED"
        .Range("E4").Formula = "=COUNTIF(" & statusRange.Address(True, True, xlA1, True) & ",""OPEN"")"
        .Range("E5").Formula = "=COUNTIF(" & statusRange.Address(True, True, xlA1, True) & ",""UNDER_REVIEW"")"
        .Range("E6").Formula = "=COUNTIF(" & statusRange.Address(True, True, xlA1, True) & ",""RESOLVED"")"
        .Range("E7").Formula = "=COUNTIF(" & statusRange.Address(True, True, xlA1, True) & ",""ADJUSTED"")"
        .Range("E8").Formula = "=COUNTIF(" & statusRange.Address(True, True, xlA1, True) & ",""ESCALATED"")"
        
        ' Total MV Impact
        .Range("A10").Value = "Total Absolute MV Impact (USD)"
        .Range("A10").Font.Bold = True
        .Range("B10").Formula = "=SUMPRODUCT(ABS(" & impactRange.Address(True, True, xlA1, True) & "))"
        .Range("B10").NumberFormat = "#,##0.00"
        
        ' Total exceptions
        .Range("A12").Value = "Total Exceptions"
        .Range("A12").Font.Bold = True
        .Range("B12").Value = tbl.ListRows.Count
        
        ' Auto-fit columns
        .Columns("A:E").AutoFit
    End With
    
    LogMacroRun "BuildSummarySheet", tbl.ListRows.Count
    
    MsgBox "Summary sheet built successfully.", vbInformation, "BuildSummarySheet"
    
    Exit Sub
    
ErrorHandler:
    MsgBox "Error building summary: " & Err.Description, vbCritical, "BuildSummarySheet"
End Sub

' =============================================================================
' ValidateSignOff
' =============================================================================
' Checks that all closed items (RESOLVED or ADJUSTED) have a reviewer,
' reviewed date, and comment. Highlights missing entries.
' =============================================================================
Public Sub ValidateSignOff()
    On Error GoTo ErrorHandler
    
    Dim ws As Worksheet
    Dim tbl As ListObject
    Dim i As Long
    Dim missingCount As Long
    Dim statusCell As Range
    Dim reviewerCell As Range
    Dim dateCell As Range
    Dim commentCell As Range
    
    Set ws = ThisWorkbook.Sheets(REVIEW_SHEET)
    
    On Error Resume Next
    Set tbl = ws.ListObjects(TABLE_NAME)
    On Error GoTo ErrorHandler
    
    If tbl Is Nothing Then
        MsgBox "No ExceptionReview table found.", vbExclamation, "ValidateSignOff"
        Exit Sub
    End If
    
    missingCount = 0
    
    ' Clear previous highlights
    tbl.ListColumns(COL_STATUS).DataBodyRange.Interior.Pattern = xlNone
    
    ' Check each row
    For i = 1 To tbl.ListRows.Count
        Set statusCell = tbl.ListColumns(COL_STATUS).DataBodyRange.Cells(i, 1)
        Set reviewerCell = tbl.ListColumns(COL_REVIEWER).DataBodyRange.Cells(i, 1)
        Set dateCell = tbl.ListColumns(COL_REVIEWED_DATE).DataBodyRange.Cells(i, 1)
        Set commentCell = tbl.ListColumns(COL_COMMENT).DataBodyRange.Cells(i, 1)
        
        ' Check if closed
        If statusCell.Value = "RESOLVED" Or statusCell.Value = "ADJUSTED" Then
            ' Check for missing fields
            If IsEmpty(reviewerCell.Value) Or reviewerCell.Value = "" Or _
               IsEmpty(dateCell.Value) Or dateCell.Value = "" Or _
               IsEmpty(commentCell.Value) Or commentCell.Value = "" Then
                statusCell.Interior.Color = RGB(255, 200, 200)
                missingCount = missingCount + 1
            End If
        End If
    Next i
    
    LogMacroRun "ValidateSignOff", tbl.ListRows.Count
    
    If missingCount > 0 Then
        MsgBox missingCount & " closed item(s) are missing reviewer, date, or comment." & vbCrLf & _
               "These rows are highlighted in red.", vbExclamation, "ValidateSignOff"
    Else
        MsgBox "All closed items have complete sign-off.", vbInformation, "ValidateSignOff"
    End If
    
    Exit Sub
    
ErrorHandler:
    MsgBox "Error validating sign-off: " & Err.Description, vbCritical, "ValidateSignOff"
End Sub

' =============================================================================
' ExportReviewedCSV
' =============================================================================
' Saves the reviewed data to reviewed_YYYYMMDD.csv for Python to ingest.
' =============================================================================
Public Sub ExportReviewedCSV()
    On Error GoTo ErrorHandler
    
    Dim ws As Worksheet
    Dim tbl As ListObject
    Dim exportPath As String
    Dim exportDate As String
    Dim tempPath As String
    Dim fso As Object
    Dim ts As Object
    
    Set ws = ThisWorkbook.Sheets(REVIEW_SHEET)
    
    On Error Resume Next
    Set tbl = ws.ListObjects(TABLE_NAME)
    On Error GoTo ErrorHandler
    
    If tbl Is Nothing Then
        MsgBox "No ExceptionReview table found.", vbExclamation, "ExportReviewedCSV"
        Exit Sub
    End If
    
    ' Generate filename with today's date
    exportDate = Format(Date, "yyyymmdd")
    tempPath = Environ("TEMP")
    exportPath = tempPath & "\reviewed_" & exportDate & ".csv"
    
    ' Export using SaveAs
    Application.DisplayAlerts = False
    
    ' Copy table to temporary workbook
    Dim tempWb As Workbook
    Dim tempWs As Worksheet
    Set tempWb = Workbooks.Add
    Set tempWs = tempWb.Sheets(1)
    
    ' Copy headers
    Dim i As Long
    For i = 1 To tbl.ListColumns.Count
        tempWs.Cells(1, i).Value = tbl.HeaderRowRange.Cells(1, i).Value
    Next i
    
    ' Copy data
    Dim dataRange As Range
    Set dataRange = tbl.DataBodyRange
    dataRange.Copy tempWs.Range("A2")
    
    ' Save as CSV
    tempWb.SaveAs exportPath, xlCSV
    tempWb.Close False
    
    Application.DisplayAlerts = True
    
    LogMacroRun "ExportReviewedCSV", tbl.ListRows.Count
    
    MsgBox "Exported " & tbl.ListRows.Count & " rows to:" & vbCrLf & exportPath, _
           vbInformation, "ExportReviewedCSV"
    
    Exit Sub
    
ErrorHandler:
    Application.DisplayAlerts = True
    MsgBox "Error exporting CSV: " & Err.Description, vbCritical, "ExportReviewedCSV"
End Sub

' =============================================================================
' LogMacroRun
' =============================================================================
' Appends an entry to the MacroLog sheet with user, timestamp, macro name,
' and row count.
' =============================================================================
Private Sub LogMacroRun(macroName As String, rowCount As Long)
    On Error Resume Next
    
    Dim ws As Worksheet
    Dim lastRow As Long
    
    ' Create MacroLog sheet if it doesn't exist
    Set ws = ThisWorkbook.Sheets(MACRO_LOG_SHEET)
    If ws Is Nothing Then
        Set ws = ThisWorkbook.Sheets.Add(After:=ThisWorkbook.Sheets(ThisWorkbook.Sheets.Count))
        ws.Name = MACRO_LOG_SHEET
        ws.Range("A1").Value = "Timestamp"
        ws.Range("B1").Value = "User"
        ws.Range("C1").Value = "Macro"
        ws.Range("D1").Value = "RowCount"
        ws.Range("A1:D1").Font.Bold = True
    End If
    
    ' Find next row
    lastRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row + 1
    
    ' Write entry
    ws.Cells(lastRow, 1).Value = Now
    ws.Cells(lastRow, 2).Value = Environ("USERNAME")
    ws.Cells(lastRow, 3).Value = macroName
    ws.Cells(lastRow, 4).Value = rowCount
    
    ' Auto-fit
    ws.Columns("A:D").AutoFit
    
    On Error GoTo 0
End Sub
