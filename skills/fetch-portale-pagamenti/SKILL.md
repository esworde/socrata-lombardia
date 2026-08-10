---
name: fetch-portale-pagamenti
description: Use when a user asks for Regione Lombardia Portale Pagamenti or pagoPA transactions for an explicit date, month, or range; daily CSV files; historical backfills; today or yesterday exports; or supplies dataset IDs 78vt-im2v, dr3m-v3by, or ne5i-i4a8.
---

# Fetch Portale Pagamenti

1. Resolve relative dates in `Europe/Rome`. Ask for the year only when it is genuinely ambiguous.
2. Resolve the absolute path of this skill directory from this `SKILL.md` location.
3. Run `python3 <skill-directory>/scripts/export_payments.py --from <date> --to <date> --output <writable-directory>`. Add `--dataset <user-value>` only when the user supplied a recognized Portale Pagamenti URL or ID.
4. Use `SOCRATA_APP_TOKEN` only when it is already available. Never request it for ordinary jobs or expose it.
5. Wait for successful completion, then report the ZIP path, day count, total records, and whether any day is `partial`.
6. On failure, report the exporter error and the preserved resumable directory. Do not claim success or improvise another downloader.
7. Read `references/schema.md` only when the user asks about fields, provenance, or output details.
