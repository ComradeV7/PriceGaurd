// fact_backtest.pq - Backtest fact table for Power BI
// Loads backtest fact from CSV with explicit types

let
    Source = Csv.Document(File.Contents(FolderPath & "\fact_backtest.csv"),
        [Delimiter=",", Columns=4, Encoding=65001, QuoteStyle=QuoteStyle.None]),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    TypedColumns = Table.TransformColumnTypes(PromotedHeaders, {
        {"fault_type", type text},
        {"injected", Int64.Type},
        {"detected", Int64.Type},
        {"recall", type number}
    })
in
    TypedColumns
