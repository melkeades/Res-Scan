from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import AppSettings, RESOURCE_TYPES
from app.db import assets_for_site, connect, delete_site_data, list_scanned_sites, preview_assets
from app.jobs import JobManager
from app.models import (
    PreviewResponse,
    ScanRequest,
    ScanStartResponse,
    ScanStatusResponse,
    SiteAssetsResponse,
    SiteDeleteResponse,
    SiteListResponse,
    SessionListResponse,
    SummaryResponse,
    ToolStatus,
)
from app.scanner import Scanner
from app.session_store import JsonStore, load_settings, save_settings
from app.tools import ToolResolutionError, resolve_and_validate_tool

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

settings_store = JsonStore(Path("data/settings.json"))
sessions_store = JsonStore(Path("data/sessions.json"))
settings = load_settings(settings_store)

settings.output_dir.mkdir(parents=True, exist_ok=True)
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.db_path.parent.mkdir(parents=True, exist_ok=True)
save_settings(settings_store, settings)

scanner = Scanner(settings)
jobs = JobManager(scanner=scanner)

app = FastAPI(title="Res-Scan")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    session_payload = sessions_store.load(default={"presets": [], "last_payload": None})
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "resource_types": RESOURCE_TYPES,
            "settings": settings.model_dump(mode="json"),
            "last_payload": session_payload.get("last_payload"),
            "presets": session_payload.get("presets", []),
        },
    )


@app.post("/api/scans", response_model=ScanStartResponse)
def start_scan(payload: ScanRequest):
    job = jobs.start(payload)
    stored = sessions_store.load(default={"presets": [], "last_payload": None})
    stored["last_payload"] = payload.model_dump(mode="json")
    sessions_store.save(stored)
    return ScanStartResponse(job_id=job.job_id, status_url=f"/api/scans/{job.job_id}")


@app.get("/api/scans/{job_id}", response_model=ScanStatusResponse)
def get_scan(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return ScanStatusResponse(
        job_id=job.job_id,
        status=job.status,  # type: ignore[arg-type]
        phase=job.phase,
        progress_pct=job.progress_pct,
        started_at=job.started_at,
        finished_at=job.finished_at,
        message=job.message,
        error=job.error,
        site_url=job.site_url,
        scan_id=job.scan_id,
    )


@app.get("/api/scans/{job_id}/summary", response_model=SummaryResponse)
def get_summary(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id")
    if job.status != "done" or not job.summary:
        raise HTTPException(status_code=409, detail="Summary unavailable until scan completes")
    return SummaryResponse(**job.summary)


@app.get("/api/assets/preview", response_model=PreviewResponse)
def get_preview(
    site_url: str = Query(..., min_length=1),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    with connect(settings.db_path) as conn:
        rows, total = preview_assets(conn, site_url=site_url, limit=limit, offset=offset)
    return PreviewResponse(rows=rows, total=total, limit=limit, offset=offset)


@app.get("/api/sites", response_model=SiteListResponse)
def get_sites():
    with connect(settings.db_path) as conn:
        rows = list_scanned_sites(conn)
    return SiteListResponse(rows=rows)


@app.delete("/api/sites", response_model=SiteDeleteResponse)
def delete_site(site_url: str = Query(..., min_length=1)):
    with connect(settings.db_path) as conn:
        result = delete_site_data(conn, site_url=site_url)
    if result["removed_assets"] == 0 and not result["removed_meta"]:
        raise HTTPException(status_code=404, detail="Unknown site_url")
    return SiteDeleteResponse(**result)


@app.get("/api/assets/site", response_model=SiteAssetsResponse)
def get_site_assets(site_url: str = Query(..., min_length=1)):
    with connect(settings.db_path) as conn:
        rows, total = assets_for_site(conn, site_url=site_url)
    return SiteAssetsResponse(site_url=site_url, total=total, rows=rows)


@app.get("/api/tools", response_model=list[ToolStatus])
def get_tool_status():
    checks = [("katana", settings.katana_path), ("httpx", settings.httpx_path)]
    statuses: list[ToolStatus] = []
    for name, configured in checks:
        try:
            resolved = resolve_and_validate_tool(name, configured)
        except ToolResolutionError as exc:
            statuses.append(
                ToolStatus(
                    name=name,
                    path=configured,
                    ok=False,
                    message=str(exc),
                )
            )
        else:
            statuses.append(
                ToolStatus(
                    name=name,
                    path=resolved.path,
                    ok=True,
                    version=resolved.version,
                )
            )
    return statuses


@app.get("/api/sessions", response_model=SessionListResponse)
def get_sessions():
    data = sessions_store.load(default={"presets": [], "last_payload": None})
    return SessionListResponse(**data)


@app.post("/api/sessions", response_model=SessionListResponse)
def save_session(payload: dict):
    data = sessions_store.load(default={"presets": [], "last_payload": None})
    presets = data.get("presets", [])
    presets.append(payload)
    data["presets"] = presets[-20:]
    sessions_store.save(data)
    return SessionListResponse(**data)
