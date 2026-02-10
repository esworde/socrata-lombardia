# Lombardia Open Data Exporter

Quick extraction of datasets from [Regione Lombardia Open Data](https://www.dati.lombardia.it/) via the Socrata SODA API.

Built for a [Southwind AI, Inc.](https://southwind.ai) use case around public payment transaction analysis.

## Prerequisites

- Python 3.8+
- A Socrata App Token (recommended for higher rate limits)

Regione Lombardia exposes its datasets through the Socrata platform. While queries work without authentication, an **App Token** raises the rate limit from 1,000 to 50,000 requests/hour. You can register for a free token at [https://www.dati.lombardia.it/profile/edit/developer_settings](https://www.dati.lombardia.it/profile/edit/developer_settings).

## Quickstart

```bash
# 1. Clone the repo
git clone https://github.com/esworde/socrata-lombardia.git
cd socrata-lombardia

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your config from the example
cp .env.example .env

# 4. Edit .env with your settings (see Configuration below)
#    At minimum, set the DATE you want to export.
#    APP_TOKEN is optional but recommended.

# 5. Run
python query.py
```

The date can also be passed as a CLI argument, which takes priority over `.env`:

```bash
python query.py 2026-02-09
```

Output is a CSV file in the current directory. The filename is configurable via `OUTPUT_FILE` in `.env` (use `{date}` as a placeholder for the date).

## Example dataset

The default configuration targets the **Portale Pagamenti** dataset (`78vt-im2v`):

> Pagamenti effettuati tramite il portale pagamentinlombardia.servizirl.it per il sistema pagoPA nella data odierna.

Dataset URL: https://www.dati.lombardia.it/resource/78vt-im2v.json

You can point `ENDPOINT` to any other Socrata dataset on dati.lombardia.it.

## Configuration

All options are set via `.env` (see `.env.example`):

| Variable | Description | Default |
|---|---|---|
| `APP_TOKEN` | Socrata API token | _(empty, unauthenticated)_ |
| `ENDPOINT` | SODA API resource URL | Portale Pagamenti dataset |
| `DATE` | Target date (`YYYY-MM-DD`) | _(none, required)_ |
| `OUTPUT_FILE` | Output filename, `{date}` is replaced with the date | `pagamenti_{date}.csv` |
| `DROP_COLUMNS` | Comma-separated columns to remove | `ora,giorno_della_settimana,modello,ultima_modifica_data` |
| `RENAME_COLUMNS` | Comma-separated `old:new` pairs | _(empty)_ |

## How it works

1. Queries the Socrata SODA API filtering by `pag_data` for the given date
2. Paginates through results in batches of 1,000
3. Enriches `pag_data` with the hour from the `ora` field
4. Drops and renames columns per configuration
5. Writes the result to a CSV file

## License

MIT
