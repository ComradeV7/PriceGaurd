// dim_date.pq - Date dimension for Power BI
// Loads date dimension from CSV with explicit types

let
    Source = Csv.Document(File.Contents(FolderPath & "\dim_date.csv"),
        [Delimiter=",", Columns=5, Encoding=65001, QuoteStyle=QuoteStyle.None]),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    TypedColumns = Table.TransformColumnTypes(PromotedHeaders, {
        {"date", type date},
        {"year", Int64.Type},
        {"month", Int64.Type},
        {"week", Int64.Type},
        {"is_business_day", type logical}
    })
in
    TypedColumns
