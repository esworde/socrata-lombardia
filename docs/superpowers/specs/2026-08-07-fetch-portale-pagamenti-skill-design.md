# Fetch Portale Pagamenti Agent Skill Design

## Summary

Turn `socrata-lombardia` into a small, open-source Agent Skill for downloading Regione Lombardia Portale Pagamenti transactions. A user supplies a calendar period in natural language or through a standalone CLI. The exporter writes one verified CSV per day, a manifest, machine-readable metadata, and a ZIP archive.

The first release supports Codex, Claude Code, Cursor, and direct CLI use. It does not claim support for arbitrary Regione Lombardia datasets.

## Goals

- Let users request Portale Pagamenti transactions without understanding Socrata, SoQL, pagination, or dataset identifiers.
- Produce reproducible daily CSV exports for an explicit date range.
- Verify completeness before reporting success.
- Keep the data-export implementation independent of any AI-agent product.
- Package one canonical skill using the open Agent Skills `SKILL.md` format.
- Install the same skill into Codex, Claude Code, or Cursor without maintaining vendor-specific copies.

## Non-goals

- Support arbitrary `dati.lombardia.it` datasets in v1.
- Generate analytics, reports, dashboards, or visualizations.
- Push datasets to GitHub or another storage service.
- Create recurring schedules or background services.
- Produce combined monthly files or alternate export formats.
- Depend on Southwind APIs or internal infrastructure.

## User experience

Users may invoke the skill explicitly or let a compatible agent select it from the task description. Representative requests include:

- “Fetch Portale Pagamenti transactions for July 2026.”
- “Download transactions from June 1 through July 31, one CSV per day.”
- “Get yesterday’s payment transactions.”
- “Use the Portale Pagamenti dataset at `dr3m-v3by` and export July.”

The skill resolves natural-language dates using the `Europe/Rome` timezone, converts them to explicit `YYYY-MM-DD` CLI arguments, runs the bundled exporter, and returns the ZIP path plus summary counts.

Users without an AI agent can run the same exporter directly:

```bash
python3 skills/fetch-portale-pagamenti/scripts/export_payments.py \
  --from 2026-07-01 \
  --to 2026-07-31 \
  --output ./exports
```

## Output contract

A successful export creates:

```text
portale-pagamenti-2026-07-01-to-2026-07-31/
├── daily/
│   ├── pagamenti_2026-07-01.csv
│   ├── pagamenti_2026-07-02.csv
│   └── ...
├── manifest.csv
└── metadata.json
```

It also creates `portale-pagamenti-2026-07-01-to-2026-07-31.zip` beside the directory.

Every requested calendar day is represented. A day with no source transactions receives a header-only CSV and a zero-count manifest entry.

The manifest contains:

```csv
date,status,transactions,filename,sha256
2026-07-01,complete,29018,pagamenti_2026-07-01.csv,<checksum>
```

`metadata.json` records the canonical source dataset and URL, requested period, generation time, timezone, output schema, total transaction count, exporter version, and whether the overall export contains a partial current day.

## Canonical data source

Use Regione Lombardia dataset `78vt-im2v` as the canonical source for all historical and current requests. It contains the complete transaction history and current-day records.

Recognize `78vt-im2v`, `dr3m-v3by`, and the derived current-day view `ne5i-i4a8` as v1 identifiers. Do not download historical periods from a current-day view. The alias resolver maps every recognized identifier or matching Lombardia URL to `78vt-im2v` before export and rejects unknown dataset identifiers.

The output schema is fixed and ordered:

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

The exporter combines the source `pag_data` day with the source `ora` value so `pag_data` retains the transaction hour. Source-only helper fields do not appear in the final CSV.

## Architecture

### Agent skill

`skills/fetch-portale-pagamenti/SKILL.md` is the agent-facing entry point. It contains only portable Agent Skills frontmatter (`name` and `description`) and vendor-neutral instructions.

The skill must:

- Recognize Portale Pagamenti, PagoPA transaction, Lombardia payment, daily CSV, and date-range requests.
- Resolve relative dates in the Lombardia timezone.
- Avoid silently guessing an ambiguous year.
- Run the bundled exporter rather than generating ad hoc download code.
- Report verified results and link the final ZIP.
- Report partial current-day results explicitly.
- Never expose authentication values.

Detailed schema notes live in `references/schema.md` so the main skill remains concise. Optional `agents/openai.yaml` metadata improves Codex presentation but does not alter the portable workflow.

### Deterministic exporter

`scripts/export_payments.py` owns all data work:

- CLI parsing and validation.
- Source URL construction.
- Expected per-day count queries.
- Stable record pagination ordered by transaction `id`.
- Network retries and rate-limit handling.
- Schema normalization and CSV writing.
- Atomic file completion.
- Per-file row-count and checksum verification.
- Manifest and metadata generation.
- ZIP packaging.
- Resume behavior.

Use the Python standard library only. The exporter requires Python 3.10 or newer and outbound HTTPS access to `www.dati.lombardia.it`.

### Installer

`install.py` copies the canonical skill directory into one or more global agent directories:

- Codex: `~/.codex/skills/fetch-portale-pagamenti/`
- Claude Code: `~/.claude/skills/fetch-portale-pagamenti/`
- Cursor: `~/.cursor/skills/fetch-portale-pagamenti/`

Supported commands are:

```bash
python3 install.py --agent codex
python3 install.py --agent claude
python3 install.py --agent cursor
python3 install.py --agent all
```

The installer copies one source of truth; the repository does not contain three skill variants. Installation replaces only a previous installation of this named skill. It must not modify unrelated skills or agent configuration.

## Data flow

1. The agent converts the user’s request into an explicit inclusive start date and end date.
2. The agent runs the exporter with those dates and an output directory.
3. The exporter validates the period and rejects future dates.
4. The exporter queries expected counts for every requested date.
5. The exporter downloads records for each day in stable `id` order.
6. The exporter writes a temporary daily CSV, verifies its schema and row count, calculates SHA-256, and atomically promotes it to its final name.
7. The exporter writes the manifest and metadata after all historical dates verify and any current-day snapshot is explicitly classified as partial.
8. The exporter creates the ZIP only when every historical day is complete and any included current day is explicitly marked partial.
9. The agent reports the output location, daily-file count, complete and partial statuses, and total records.

## Reliability and failure behavior

- Reject malformed dates, a reversed period, and dates after today in `Europe/Rome`.
- Permit today, but mark it `partial` because the dataset changes throughout the day.
- Retry connection failures, HTTP 429 responses, and HTTP 5xx responses using bounded exponential backoff.
- Never retry permanent validation or HTTP 4xx failures other than 429.
- Use stable ordering and deduplicate by transaction `id` across pages.
- Write `.part` files and rename them only after verification.
- Reuse an existing daily CSV only when its manifest count and checksum both verify; otherwise download that day again.
- Re-query historical counts before final packaging and require exact equality with the exported row count.
- For today, record the exported row count and the source count observed at the end of the run, but do not require equality because new transactions can arrive during export. Keep its status `partial`.
- Retry a count mismatch for the affected day. If it still fails, retain verified days for resuming, exit nonzero, and do not create the final ZIP.
- Keep the optional Socrata token in the `SOCRATA_APP_TOKEN` environment variable. Never accept it as a command-line value, print it, or write it to metadata.
- Emit plain-language errors to stderr and progress information to stdout.

## Cross-agent compatibility

The canonical skill follows the open Agent Skills directory format and avoids client-specific frontmatter or commands. Relative resource references are resolved from the directory containing `SKILL.md`.

V1 compatibility claims are limited to:

- Codex standalone skills.
- Claude Code personal skills.
- Cursor personal skills.
- Direct Python CLI execution.

The implementation does not add duplicated `CLAUDE.md`, Cursor rules, or `AGENTS.md` adapters. Those mechanisms are always-on configuration rather than portable, progressively loaded skills.

## Repository layout

```text
socrata-lombardia/
├── README.md
├── LICENSE
├── install.py
├── skills/
│   └── fetch-portale-pagamenti/
│       ├── SKILL.md
│       ├── agents/
│       │   └── openai.yaml
│       ├── scripts/
│       │   └── export_payments.py
│       └── references/
│           └── schema.md
└── tests/
    ├── test_export_payments.py
    └── test_install.py
```

Remove the repository’s old single-day exporter and dependency files after equivalent behavior is covered by the new exporter. Preserve the MIT license. Rewrite the top-level README around installation, agent examples, direct CLI use, output structure, optional authentication, and limitations.

## Testing and acceptance criteria

### Automated tests

- Date validation, inclusive date iteration, relative-date handoff assumptions, and current-day status.
- Alias mapping from `dr3m-v3by` to `78vt-im2v`.
- CSV quoting, fixed header order, hour enrichment, zero-row days, hashes, manifests, metadata, and ZIP contents.
- Pagination, duplicate IDs, rate limits, retry exhaustion, permanent HTTP failures, and count mismatches using a local mock HTTP server.
- Atomic writes and resume behavior after simulated interruption.
- Installer targeting for Codex, Claude Code, Cursor, and all-agent mode using temporary home directories.
- Confirmation that installing one skill does not modify unrelated files.

### Skill validation

- Validate the canonical skill against the Agent Skills specification.
- Validate Codex-specific optional metadata separately.
- Confirm `SKILL.md` has portable frontmatter and no vendor-only invocation syntax.

### Live smoke test

- Export one small, completed historical day from `78vt-im2v`.
- Reconcile source and CSV row counts.
- Validate the checksum, manifest, metadata, and ZIP archive.
- Run the same exporter without a Socrata token.

### Agent testing

- Install the skill into each locally available supported agent.
- Start a fresh agent session and issue only a realistic request such as “Download Portale Pagamenti transactions for June 23, 2026.”
- Verify the agent selects the skill, runs the bundled exporter, and returns the correct artifact rather than writing replacement download logic.
- If a supported client is unavailable locally, test its installation layout in a temporary home and state that runtime invocation was not executed on that client.

The release is ready for the user’s test when all automated tests, structural validation, the live smoke test, and at least one fresh-agent invocation pass.

## Release sequence

1. Implement and test on branch `codex/fetch-portale-pagamenti-skill` in the public repository history.
2. Install the skill locally for the user’s preferred agent and provide a concrete test prompt.
3. Let the user inspect the generated export and skill behavior.
4. Make any corrections discovered during user testing.
5. Push to GitHub only after the user confirms the tested behavior is ready.
