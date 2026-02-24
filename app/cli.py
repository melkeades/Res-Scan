from __future__ import annotations

from pathlib import Path

import uvicorn

from app.session_store import JsonStore, load_settings


def main() -> None:
    settings = load_settings(JsonStore(path=Path("data/settings.json")))
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
