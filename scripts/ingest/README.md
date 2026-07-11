# Ingestion (self-owned)

Batch ingestion that parses official CMU sources into our normalized models. It
runs **off the request path** — scheduled batch work, not a per-request call.

## Why we parse it ourselves

There is **no official hosted CMU or ScottyLabs API** to depend on. The
`cmu_course_api` PyPI package was last updated in **2019** and its
DOM-position-dependent selectors are stale against today's pages; the ScottyLabs
`cmucourses` repo is a full web app, not a callable API. So ingestion is
**self-owned**: we write our own parsers against the official sources and assume
none of the old selectors still work. We may read the 2019 package only as a
*reference* for where the data lives.

The payoff: no dependency on anyone's uptime or an abandoned endpoint. When CMU
redesigns a page, it's a parser fix on our side (in `parsers.py`) — under our
control — not an outage we can't fix.

## Sources

| Source | Parses to | Where |
|---|---|---|
| **Schedule of Classes** (SOC) | sections, meeting days/times, units | `SOC_URL` in `ingest.py` |
| **Course Catalog** | descriptions + prerequisite trees | `CATALOG_URL` in `ingest.py` |
| **FCE export** | workload hours, ratings | manual CSV (see caveat) |

Prerequisite *text* is parsed into the models' AND/OR tree. Text we cannot model
(e.g. "Grade of C or better in 21-120") becomes a `PrereqUnparsed` node, so the
classifier defaults that course to **`unconfirmed`, never `blocked`** — the
non-negotiable safety rule.

## Manual-FCE caveat

The FCE portal is **auth-gated**, so v1 uses a **manual CSV export** (header:
`course_num,workload_hours,rating`). This is a stated limitation, not a hidden
assumption. FCE is read from a local CSV **whether or not** you're in dry-run;
courses missing an FCE row default to `0.0` workload/rating. An authenticated
integration is future work.

## Dry-run (fixtures, no network)

`--dry-run` sources the SOC and Catalog from committed fixtures under
`data/fixtures/` instead of the network, so tests and CI never depend on CMU's
site being up:

- `data/fixtures/soc_sample.html`
- `data/fixtures/catalog_sample.html`
- `data/fixtures/fce_sample.csv`

Our parsers target the structure captured in these fixtures. When CMU changes its
markup, update the parser **and** refresh the fixture from a real page.

## How to refresh

```bash
# Dry-run: parse fixtures, write normalized JSON (same shape as data/samples).
uv run --project backend python scripts/ingest/cli.py --dry-run --out out.json

# Live: fetch the official sources; FCE still from a manual export.
uv run --project backend python scripts/ingest/cli.py \
    --fce data/fixtures/fce_sample.csv --out out.json
```

To refresh a fixture after a CMU page change: save the relevant page HTML into
`data/fixtures/`, adjust the selectors in `parsers.py` if needed, and re-run the
ingestion test (`backend/tests/test_ingest.py`) until models validate again.

## Files

- `parsers.py` — the SOC / Catalog / FCE / prereq-text parsers (ours).
- `ingest.py` — merges parsed sources into `Course` models; `--dry-run` + writer.
- `cli.py` — argparse entry point.
