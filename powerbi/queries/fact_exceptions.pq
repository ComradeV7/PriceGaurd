// fact_exceptions.pq - Exceptions fact table for Power BI
// Loads exceptions fact from CSV with explicit types

let
    Source = Csv.Document(File.Contents(FolderPath & "\fact_exceptions.csv"),
        [Delimiter=",", Columns=12, Encoding=65001, QuoteStyle=QuoteStyle.None]),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    TypedColumns = Table.TransformColumnTypes(PromotedHeaders, {
        {"exception_id", type text},
        {"date", type date},
        {"position_id", type text},
        {"check_name", type text},
        {"severity", type text},
        {"status", type text},
        {"deviation_bps", type number},
        {"mv_impact_usd", type number},
        {"opened_date", type date},
        {"resolved_date", type date},
        {"age_days", Int64.Type},
        {"is_simulated", type logical}
    })
in
    TypedColumns
