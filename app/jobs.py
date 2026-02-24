from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models import ScanRequest
from app.scanner import Scanner


@dataclass(slots=True)
class JobState:
    job_id: str
    status: str = "queued"
    phase: str = "queued"
    progress_pct: int = 0
    message: str = ""
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    site_url: str | None = None
    scan_id: str | None = None
    summary: dict | None = None


class JobManager:
    def __init__(self, scanner: Scanner):
        self._scanner = scanner
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()

    def start(self, request: ScanRequest) -> JobState:
        job_id = uuid.uuid4().hex
        scan_id = uuid.uuid4().hex
        state = JobState(job_id=job_id, scan_id=scan_id, status="running", phase="starting")
        state.started_at = datetime.now(timezone.utc)
        state.site_url = request.base_url
        with self._lock:
            self._jobs[job_id] = state

        thread = threading.Thread(
            target=self._run,
            args=(state.job_id, scan_id, request),
            daemon=True,
        )
        thread.start()
        return state

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _run(self, job_id: str, scan_id: str, request: ScanRequest) -> None:
        try:
            result = self._scanner.run_scan(
                scan_id=scan_id,
                request=request,
                progress=lambda phase, pct, msg: self._update(job_id, phase, pct, msg),
            )
        except Exception as exc:
            self._fail(job_id, str(exc))
            return

        with self._lock:
            state = self._jobs[job_id]
            state.status = "done"
            state.phase = "done"
            state.progress_pct = 100
            state.message = "Scan completed"
            state.finished_at = datetime.now(timezone.utc)
            state.site_url = result.get("site_url")
            state.summary = result.get("summary")

    def _update(self, job_id: str, phase: str, pct: int, msg: str) -> None:
        with self._lock:
            state = self._jobs[job_id]
            state.phase = phase
            state.progress_pct = max(0, min(100, pct))
            state.message = msg

    def _fail(self, job_id: str, error: str) -> None:
        with self._lock:
            state = self._jobs[job_id]
            state.status = "failed"
            state.phase = "failed"
            state.error = error
            state.message = "Scan failed"
            state.finished_at = datetime.now(timezone.utc)

