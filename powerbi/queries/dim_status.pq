// dim_status.pq - Status dimension for Power BI
// Loads status dimension from CSV with explicit types

let
    Source = Csv.Document(File.Contents(FolderPath & "\dim_status.csv"),
        [Delimiter=",", Columns=3, Encoding=65001, QuoteStyle=QuoteStyle.None]),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    TypedColumns = Table.TransformColumnTypes(PromotedHeaders, {
        {"status", type text},
        {"sort_order", Int64.Type},
        {"is_open", type logical}
    })
in
    TypedColumns
