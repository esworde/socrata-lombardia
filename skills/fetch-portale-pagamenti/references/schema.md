# Schema and output contract

## Source

The recognized Portale Pagamenti IDs are `78vt-im2v`, `dr3m-v3by`, and
`ne5i-i4a8`. Each resolves to the canonical historical source:
`https://www.dati.lombardia.it/resource/78vt-im2v.json`.

## Daily CSV fields

Each daily CSV uses this fixed header and field order:

1. `id`
2. `psp_id`
3. `psp_desc`
4. `ente_cf`
5. `ente_desc`
6. `ente_cap`
7. `ente_prov`
8. `pag_importo`
9. `pag_data`
10. `tipo_dovuto`

The source `ora` value enriches `pag_data` with an hour in the form
`YYYY-MM-DDTHH:00:00.000`; `ora` is not an output field. A zero-row day still
creates a CSV containing this header only.

## Delivery files

`manifest.csv` has the columns `date`, `status`, `transactions`, `filename`,
and `sha256`.

`metadata.json` contains `exporter_version`, `dataset` (`requested`,
`canonical_id`, `url`), `period` (`from`, `to`), `timezone`, `generated_at`,
`schema`, `files`, `transactions`, `contains_partial_day`, and
`current_day_source_count_observed_at_end`.

Historical days are `complete` only after reconciliation with the source.
Today is always marked `partial`, including when its observed counts match,
because records can still change.
