// fact_marks.pq - Marks fact table for Power BI
// Loads marks fact from CSV with explicit types

let
    Source = Csv.Document(File.Contents(FolderPath & "\fact_marks.csv"),
        [Delimiter=",", Columns=6, Encoding=65001, QuoteStyle=QuoteStyle.None]),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    TypedColumns = Table.TransformColumnTypes(PromotedHeaders, {
        {"date", type date},
        {"position_id", type text},
        {"mark", type number},
        {"reference_price", type number},
        {"deviation_bps", type number},
        {"mv_usd", type number}
    })
in
    TypedColumns
