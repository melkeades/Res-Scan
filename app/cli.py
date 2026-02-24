from __future__ import annotations

from pathlib import Path

import uvicorn

from app.session_store import JsonStore, load_settings


def main() -> None:
    settings = load_settings(JsonStore(path=Path("data/settings.json")))
    db_path = settings.db_path
    suffix = db_path.suffix.lower()
    if suffix in {".sqlite", ".db", ".sqlite3"}:
        db_backend = "SQLite"
    elif suffix == ".duckdb":
        db_backend = "DuckDB"
    else:
        db_backend = "Unknown"
    print(f"[Res-Scan] DB backend: {db_backend} | file: {db_path.resolve()}")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
