from __future__ import annotations

import json
import threading
from pathlib import Path

from app.config import AppSettings


class JsonStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def load(self, default):
        if not self.path.exists():
            return default
        with self._lock:
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return default

    def save(self, payload) -> None:
        with self._lock:
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temp.replace(self.path)


def load_settings(store: JsonStore) -> AppSettings:
    raw = store.load(default={})
    try:
        settings = AppSettings.model_validate(raw)
    except Exception:
        settings = AppSettings()

    # Migrate old DuckDB filename defaults to SQLite.
    if settings.db_path.suffix.lower() == ".duckdb":
        settings.db_path = settings.db_path.with_suffix(".sqlite")
    return settings


def save_settings(store: JsonStore, settings: AppSettings) -> None:
    store.save(settings.model_dump(mode="json"))
