from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ResourceType = Literal["css", "js", "images", "fonts", "video", "docs"]

RESOURCE_TYPES: tuple[ResourceType, ...] = (
    "css",
    "js",
    "images",
    "fonts",
    "video",
    "docs",
)


class AppSettings(BaseModel):
    output_dir: Path = Path("out")
    data_dir: Path = Path("data")
    db_path: Path = Path("out/assets.sqlite")
    katana_path: str | None = None
    httpx_path: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000


class SessionPreset(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    payload: dict
