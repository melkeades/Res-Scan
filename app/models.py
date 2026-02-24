from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from app.config import RESOURCE_TYPES, ResourceType


class ScanRequest(BaseModel):
    base_url: str = Field(min_length=1)
    resource_types: list[ResourceType] | None = None
    depth: int = Field(default=4, ge=1, le=12)
    include_regex: str | None = None
    exclude_regex: str | None = None
    max_pages: int = Field(default=5000, ge=1, le=200_000)
    timeout_seconds: int = Field(default=20, ge=1, le=180)
    follow_redirects: bool = True
    respect_robots: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"}:
            raise ValueError("base_url must start with http:// or https://")
        if not parts.netloc:
            raise ValueError("base_url must include a host")
        return value.strip()

    @field_validator("resource_types")
    @classmethod
    def validate_resource_types(
        cls, value: list[ResourceType] | None
    ) -> list[ResourceType] | None:
        if value is None:
            return None
        unique = []
        for item in value:
            if item not in RESOURCE_TYPES:
                raise ValueError(f"Unsupported resource type: {item}")
            if item not in unique:
                unique.append(item)
        return unique or None


class ScanStartResponse(BaseModel):
    job_id: str
    status_url: str


class ScanStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "failed"]
    phase: str
    progress_pct: int = Field(ge=0, le=100)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str = ""
    error: str | None = None
    site_url: str | None = None
    scan_id: str | None = None


class AssetPreviewRow(BaseModel):
    site_url: str
    page_url: str
    asset_url: str
    dom_path: str
    asset_attr: str
    attr_occurrence: int
    instance_key: str
    resource_type: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    content_length: int | None = None
    scan_id: str
    discovered_at: datetime


class PreviewResponse(BaseModel):
    rows: list[AssetPreviewRow]
    total: int
    limit: int
    offset: int


class SummaryResponse(BaseModel):
    by_type: list[dict]
    totals: dict


class ToolStatus(BaseModel):
    name: str
    path: str | None
    ok: bool
    version: str | None = None
    message: str | None = None


class SessionListResponse(BaseModel):
    presets: list[dict]
    last_payload: dict | None = None


class SiteListRow(BaseModel):
    site_url: str
    site_name: str
    resource_rows: int
    scanned_at: datetime | None = None


class SiteListResponse(BaseModel):
    rows: list[SiteListRow]


class SiteAssetRow(BaseModel):
    page_url: str
    asset_url: str
    dom_path: str
    asset_attr: str
    attr_occurrence: int
    instance_key: str
    resource_type: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    content_length: int | None = None
    scan_id: str
    discovered_at: datetime


class SiteAssetsResponse(BaseModel):
    site_url: str
    total: int
    rows: list[SiteAssetRow]
