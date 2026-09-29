// dim_severity.pq - Severity dimension for Power BI
// Loads severity dimension from CSV with explicit types

let
    Source = Csv.Document(File.Contents(FolderPath & "\dim_severity.csv"),
        [Delimiter=",", Columns=2, Encoding=65001, QuoteStyle=QuoteStyle.None]),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    TypedColumns = Table.TransformColumnTypes(PromotedHeaders, {
        {"severity", type text},
        {"sort_order", Int64.Type}
    })
in
    TypedColumns
