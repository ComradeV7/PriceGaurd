// dim_instrument.pq - Instrument dimension for Power BI
// Loads instrument dimension from CSV with explicit types

let
    Source = Csv.Document(File.Contents(FolderPath & "\dim_instrument.csv"),
        [Delimiter=",", Columns=6, Encoding=65001, QuoteStyle=QuoteStyle.None]),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    TypedColumns = Table.TransformColumnTypes(PromotedHeaders, {
        {"instrument_id", type text},
        {"ticker", type text},
        {"name", type text},
        {"asset_class", type text},
        {"fv_level", Int64.Type},
        {"currency", type text}
    })
in
    TypedColumns
