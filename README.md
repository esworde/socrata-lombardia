# Fetch Portale Pagamenti

## What this is

A portable Agent Skill and deterministic CLI for verified Regione Lombardia
Portale Pagamenti exports.

## The problem

Public records still require discovering the historical source, resolving
current-day aliases, building Socrata queries, paginating safely, retrying
transient failures, and proving daily completeness. Coding agents otherwise
improvise this work repeatedly.

## What this solves

Natural-language or CLI requests produce one CSV per day, `manifest.csv`,
`metadata.json`, and one ZIP delivery artifact.

## Installation

The canonical skill is `skills/fetch-portale-pagamenti`. Install that same copy
for a supported coding agent:

```bash
python3 install.py --agent codex
python3 install.py --agent claude
python3 install.py --agent cursor

# Direct Python use from the canonical skill
python3 skills/fetch-portale-pagamenti/scripts/export_payments.py \
  --from 2026-06-03 --to 2026-06-05 --output exports
```

The exporter uses `SOCRATA_APP_TOKEN` only when that optional environment
variable is already set; no token is required for ordinary exports.

## Examples

Ask an agent: “Download Portale Pagamenti transactions for 3–5 June 2026.”

Ask an agent: “Use `$fetch-portale-pagamenti` to export yesterday’s Lombardia
pagoPA transactions.”

Or run the CLI directly:

```bash
python3 skills/fetch-portale-pagamenti/scripts/export_payments.py \
  --from 2026-06-03 --to 2026-06-05 --output exports
```

## Trust guarantees

Historical days are reconciled against the source. The exporter uses stable
pagination, retries transient failures, records checksums, completes files
atomically, resumes verified work, writes header-only CSVs for zero-row days,
and marks the current day `partial`.

## Output and schema

```text
exports/
├── portale-pagamenti-2026-06-03-to-2026-06-05/
│   ├── daily/pagamenti_2026-06-03.csv
│   ├── manifest.csv
│   └── metadata.json
└── portale-pagamenti-2026-06-03-to-2026-06-05.zip
```

Each CSV has the fixed fields `id`, `psp_id`, `psp_desc`, `ente_cf`,
`ente_desc`, `ente_cap`, `ente_prov`, `pag_importo`, `pag_data`, and
`tipo_dovuto`. See [the schema reference](skills/fetch-portale-pagamenti/references/schema.md)
for provenance and delivery details.

## Focused v1

This skill supports Portale Pagamenti only. It does not claim support for
arbitrary Socrata or Regione Lombardia datasets.

## Future direction

These foundations may later inform a broader skill for other Lombardia
open-data datasets, guided by real use cases.

## Development and license

Requires Python 3.10+ and has zero dependencies. Run the tests with:

```bash
python3 -m unittest discover -s tests -v
```

Released under the [MIT License](LICENSE).
