## Res-Scan

Res-Scan is a local web app for crawling a site and building an asset inventory in DuckDB.  
You enter a URL, optional resource filters, and scan parameters, then the app runs Katana for crawl discovery and ProjectDiscovery `httpx` for HTTP metadata enrichment.

The data model tracks asset instances by exact page position (`dom_path` + occurrence), so repeated references on the same page are preserved as separate rows.  
Re-scans update the site in place: stale rows are removed and current rows are written back, keeping the database aligned with the latest scan.

The UI has two tabs:
- `Scan`: run a new scan and view progress/summary.
- `View`: browse scanned sites, open full resource tables, filter/sort columns, and delete a site from the DB.

### Install

#### 1) Install `uv`

Windows (PowerShell):
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

macOS/Linux:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 2) Install Python dependencies

From project root:
```powershell
uv sync --no-config
```

#### 3) Install DuckDB (CLI optional but recommended)

If you only use the app, the Python `duckdb` package is already installed by `uv sync`.  
Optional CLI install:

Windows (winget):
```powershell
winget install DuckDB.cli
```

macOS (Homebrew):
```bash
brew install duckdb
```

Linux (Debian/Ubuntu):
```bash
sudo apt-get update
sudo apt-get install duckdb
```

#### 4) Install Katana

Requires Go. Then install:
```powershell
go install github.com/projectdiscovery/katana/cmd/katana@latest
```

#### 5) Install ProjectDiscovery `httpx`

Requires Go. Then install:
```powershell
go install github.com/projectdiscovery/httpx/cmd/httpx@latest
```

Note: this is **ProjectDiscovery `httpx` binary**, not Python `httpx`.

#### 6) Verify tools

```powershell
katana -version
httpx -version
```

### Run

```powershell
uv run res-scan
```

Open `http://127.0.0.1:8000`.

### Tests

```powershell
uv run --no-config pytest
```
