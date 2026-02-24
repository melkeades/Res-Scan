# Website Asset Inventory: Plan + Minimal UI

## Goal
Build a small local tool that:

- Crawls a website and discovers asset URLs (CSS/JS/images/fonts/videos/etc.)
- Captures **where each asset was found** (page/source URL)
- Enriches assets with HTTP metadata (type, size, status)
- Stores everything in a single local database file (DuckDB)
- Lets you **re-query** using new include/exclude masks without re-crawling
- Lets you **refresh** the DB after a site update (re-run crawl/probe)

This is designed to keep your custom codebase minimal by delegating crawling/probing to maintained tools.

## Non-goals
- Full authenticated end-to-end app crawling (Playwright-style user journeys)
- Rendering correctness audits (CSS/layout) or content diffs
- Asset downloading / mirroring (optional later)

## Tech choices
### Core tooling
- **Katana** (ProjectDiscovery) for crawling + extraction
  - https://github.com/projectdiscovery/katana
  - https://docs.projectdiscovery.io/opensource/katana/running
- **httpx** (ProjectDiscovery) for probing URLs (status, content-type, content-length)
  - https://docs.projectdiscovery.io/opensource/httpx/usage
- **DuckDB** for a single-file local analytics DB that can ingest JSONL easily
  - https://duckdb.org/docs/stable/clients/python/overview.html
  - https://duckdb.org/docs/stable/data/json/loading_json.html
- Optional local querying UI (pick one):
  - DuckDB UI extension (local) https://duckdb.org/docs/stable/core_extensions/ui
  - DBeaver (DuckDB JDBC) https://duckdb.org/docs/stable/guides/sql_editors/dbeaver.html

### Orchestrator language
Use **Python** as the glue (thin orchestrator). It only needs:
- spawn processes (no shell scripts)
- parse JSONL lightly
- load into DuckDB and build a few tables/views

Refs:
- Python subprocess https://docs.python.org/3/library/subprocess.html

## High-level architecture

1) **Crawl**
- Run katana against `base_url`
- Output:
  - `katana.jsonl` (full structured crawl records)
  - `asset_urls.txt` (deduped list of asset URLs to probe)

2) **Probe**
- Run httpx on `asset_urls.txt`
- Output:
  - `httpx.jsonl` (metadata per URL)

3) **Build DB**
- Ingest both JSONL files into DuckDB
- Create canonical tables:
  - `assets` (joined view: asset_url + page_url/source + content_type/length/status)
  - `pages` (optional: page-level rollups)
  - `runs` (optional: track refresh timestamps + config snapshot)

4) **Query**
- Users run SQL in DuckDB UI / DBeaver, or via a minimal built-in UI.

5) **Refresh**
- Re-run crawl/probe and `CREATE OR REPLACE` tables
- Keep the DB file path stable (ex: `assets.duckdb`)

## Data outputs

### On disk
- `out/katana.jsonl`
- `out/asset_urls.txt`
- `out/httpx.jsonl`
- `out/assets.duckdb`

### DuckDB tables (minimum)

#### `katana_raw`
Raw katana JSONL rows.

#### `httpx_raw`
Raw httpx JSONL rows.

#### `assets` (canonical)
One row per discovered asset occurrence (or per unique asset—see below).

Recommended columns:
- `asset_url` (TEXT)
- `page_url` (TEXT) — where it was discovered from (katana `source` if present)
- `discovery_type` (TEXT) — optional: tag/attribute context (script/src/link/href/etc.)
- `status_code` (INT)
- `content_type` (TEXT)
- `content_length` (BIGINT)
- `first_seen_run_id` (TEXT/UUID) — optional
- `last_seen_run_id` (TEXT/UUID) — optional

**Two practical modeling options:**

A) **Occurrence table** (default)
- If the same asset is referenced by multiple pages, keep multiple rows.
- Pro: easy “asset → pages” mapping.
- Con: duplicates for rollups.

B) **Normalized**
- `asset_urls` (unique assets)
- `asset_refs` (page → asset_url)
- Pro: cleaner stats.
- Con: slightly more schema.

Given your “small DB” goal, start with **A** and add views for unique rollups.

## Mask strategy

You want to modify include/exclude masks without lots of code.

### Where masks live
1) **Crawler-time masks** (katana)
- Use when you want to reduce crawl output size/noise early.
- Examples:
  - extension allowlist (assets only)
  - exclude tracking parameters

2) **Query-time masks** (DuckDB SQL)
- Use when you want to explore different masks interactively.
- This is the main “iterate mask quickly” workflow.

### Mask inputs
Support both:
- **positive include**: extensions, regex patterns
- **negative exclude**: regex patterns

Persist mask settings per run (optional) in a `runs` table for auditability.

## Recommended default crawl/probe settings

### Katana
- Depth: 3–6 depending on site
- Enable JS crawl helpers if needed (optional): JS parsing / headless hybrid
- Keep JSONL output (needed for page→asset mapping)

Docs:
- https://github.com/projectdiscovery/katana
- https://docs.projectdiscovery.io/opensource/katana/running

### httpx
- Prefer `HEAD` for speed
- Capture status code, content-type, content-length

Docs:
- https://docs.projectdiscovery.io/opensource/httpx/usage

## Minimal UI (very small)

You asked for “minimal UI” only:

### UI goals
- Single input: **Base URL**
- Controls:
  - Include extensions (comma list)
  - Include regex (optional)
  - Exclude regex (optional)
  - Depth (optional)
  - Toggle headless crawl (optional)
- Actions:
  - **Run scan**
  - **Refresh scan** (same as run, but overwrites)
- Outputs:
  - Status/progress
  - Summary stats
  - Preview table of results
  - Link/command to open DB in DuckDB UI

### Minimal UI implementation options

Option 1 (lowest code): **No custom UI**, just open DuckDB UI
- The orchestrator prints:
  - output folder
  - DB path
  - a few “starter queries”
- You open DuckDB UI and query `assets`.

DuckDB UI docs:
- https://duckdb.org/docs/stable/core_extensions/ui

Option 2 (still small): a tiny local web server
- Python: FastAPI/Starlette
  - one page with a form
  - `POST /scan` triggers the pipeline
  - `GET /status` returns progress
  - `GET /preview` returns first N rows
- Keep UI dead-simple: one HTML page + fetch calls.

(If you do Option 2, keep all heavy logic in the same orchestrator module; don’t build a framework.)

### UI endpoints (if Option 2)
- `GET /` — form
- `POST /scan` — start scan
- `GET /status` — { phase: crawl|probe|db, pct, logs_tail }
- `GET /summary` — totals by content_type + top largest
- `GET /preview?limit=100` — sample rows

## Refresh behavior

### Basic refresh (stateless)
- Re-run crawl/probe
- `CREATE OR REPLACE TABLE ...` in DuckDB
- Old data is overwritten.

### Optional history (if you want diffs)
- Add a `run_id` (UUID) per scan
- Append raw tables with `run_id`
- Maintain a view `assets_latest` filtering `last_run_id`
- Enables:
  - diff assets between deploys
  - detect new/lost assets

## Example queries (for scrubbing)

### Biggest assets
```sql
SELECT asset_url, content_type, content_length
FROM assets
WHERE content_length IS NOT NULL
ORDER BY content_length DESC
LIMIT 50;
```

### Total bytes by content type
```sql
SELECT content_type, COUNT(*) AS n, SUM(content_length) AS bytes
FROM assets
GROUP BY 1
ORDER BY bytes DESC;
```

### Assets referenced by a specific page
```sql
SELECT page_url, asset_url, content_type, content_length
FROM assets
WHERE page_url = 'https://example.com/some-page'
ORDER BY content_length DESC;
```

### Apply masks in SQL (include + exclude)
```sql
SELECT asset_url, content_type, content_length
FROM assets
WHERE asset_url ~ '.*\\.(js|css)(\\?|$)'
  AND asset_url !~ '.*(vendor|chunk|analytics).*'
ORDER BY content_length DESC;
```

## Implementation outline (Python)

### File layout
- `app/scan.py` — pipeline orchestration: crawl → probe → build_db
- `app/config.py` — config dataclass + defaults
- `app/db.py` — DuckDB table creation + views
- `app/ui.py` — optional minimal UI (if you choose Option 2)
- `out/` — outputs

### Pipeline phases
1) `run_katana(config) -> katana.jsonl`
2) `extract_urls(katana.jsonl) -> asset_urls.txt`
3) `run_httpx(asset_urls.txt) -> httpx.jsonl`
4) `ingest_duckdb(katana.jsonl, httpx.jsonl) -> assets table`

### Keep code small by design
- No crawling logic in Python
- No HTTP fetching logic in Python
- Only:
  - spawn
  - parse JSONL (just enough to build URL list)
  - load & join in DuckDB

## Edge cases to handle

- **Relative URLs**: katana generally normalizes, but verify.
- **Query strings**: treat `file.js?v=123` as same asset? Decide.
  - Simple approach: keep full URL, add derived `asset_url_stripped` column later.
- **HEAD unsupported**: some servers don’t return content-length on HEAD.
  - Option: fall back to GET for missing size (optional, controlled).
- **CDNs and third-party assets**: decide include/exclude by host.
- **SPAs**: if katana misses assets because of JS-only navigation, enable hybrid headless crawling (if needed).

## How you’ll use it day-to-day

1) Run scan:
- produces `out/assets.duckdb`

2) Open DB:
- DuckDB UI (`duckdb -ui`) then attach/open the file
- or DBeaver and point to the file

3) Iterate on masks:
- mostly in SQL (`WHERE` clauses)
- optionally adjust crawler masks to reduce noise

4) After deploy:
- re-run scan (refresh)
- compare results if you keep run history

## Tooling installation notes (links)
- Katana: https://github.com/projectdiscovery/katana
- Katana docs: https://docs.projectdiscovery.io/opensource/katana/running
- httpx docs: https://docs.projectdiscovery.io/opensource/httpx/usage
- DuckDB Python: https://duckdb.org/docs/stable/clients/python/overview.html
- DuckDB JSON loading: https://duckdb.org/docs/stable/data/json/loading_json.html
- DuckDB UI: https://duckdb.org/docs/stable/core_extensions/ui
- DBeaver guide: https://duckdb.org/docs/stable/guides/sql_editors/dbeaver.html

## Optional future upgrades (still low maintenance)
- Keep scan history and compute diffs (new/lost assets, size changes)
- Export reports (CSV/Parquet)
- Add host-based allow/deny lists
- Enrich with response caching headers (cache-control, etag) via httpx output options (if needed)
- Add a “download largest N assets” helper (separate mode)

