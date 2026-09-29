// dim_book.pq - Book dimension for Power BI
// Loads book dimension from CSV with explicit types

let
    Source = Csv.Document(File.Contents(FolderPath & "\dim_book.csv"),
        [Delimiter=",", Columns=1, Encoding=65001, QuoteStyle=QuoteStyle.None]),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    TypedColumns = Table.TransformColumnTypes(PromotedHeaders, {
        {"book", type text}
    })
in
    TypedColumns
