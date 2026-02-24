from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from time import perf_counter
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from app.config import AppSettings, ResourceType
from app.db import connect, replace_site_assets, summary_for_site
from app.extractor import AssetInstance, extract_asset_instances, normalize_identity_url
from app.models import ScanRequest
from app.tools import resolve_and_validate_tool

ProgressCallback = Callable[[str, int, str], None]


class Scanner:
    def __init__(self, settings: AppSettings):
        self.settings = settings

    def run_scan(
        self, *, scan_id: str, request: ScanRequest, progress: ProgressCallback
    ) -> dict:
        overall_start = perf_counter()
        stage_durations: dict[str, float] = {}
        now = datetime.now(timezone.utc)
        run_dir = self.settings.output_dir / scan_id
        run_dir.mkdir(parents=True, exist_ok=True)

        progress("validate", 5, "Resolving scanner binaries")
        stage_start = perf_counter()
        katana = resolve_and_validate_tool("katana", self.settings.katana_path)
        httpx = resolve_and_validate_tool("httpx", self.settings.httpx_path)
        stage_durations["validate"] = perf_counter() - stage_start

        base_site_url = normalize_site_origin(request.base_url)
        if not base_site_url:
            raise ValueError("Unable to normalize base_url")
        site_host = urlsplit(base_site_url).hostname or ""

        robots = RobotsGate(base_site_url, enabled=request.respect_robots)

        katana_jsonl = run_dir / "katana.jsonl"
        asset_urls_txt = run_dir / "asset_urls.txt"
        httpx_jsonl = run_dir / "httpx.jsonl"
        instances_jsonl = run_dir / "instances.jsonl"

        progress("crawl", 15, "Running katana crawl")
        stage_start = perf_counter()
        self._run_katana(
            tool_path=katana.path,
            request=request,
            out_file=katana_jsonl,
        )
        stage_durations["crawl"] = perf_counter() - stage_start

        include_pattern = (
            re.compile(request.include_regex) if request.include_regex else None
        )
        exclude_pattern = (
            re.compile(request.exclude_regex) if request.exclude_regex else None
        )
        selected_types = (
            set(request.resource_types) if request.resource_types else None
        )

        progress("extract", 45, "Extracting asset instances from crawled pages")
        stage_start = perf_counter()
        instances = self._extract_instances(
            site_url=base_site_url,
            site_host=site_host,
            katana_jsonl=katana_jsonl,
            robots=robots,
            max_pages=request.max_pages,
            selected_types=selected_types,
            include_pattern=include_pattern,
            exclude_pattern=exclude_pattern,
            discovered_at=now,
        )
        deduped = dedupe_instances_by_key(instances)
        stage_durations["extract"] = perf_counter() - stage_start

        instances_jsonl.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in deduped),
            encoding="utf-8",
        )
        unique_assets = sorted({item["asset_url"] for item in deduped})
        asset_urls_txt.write_text("\n".join(unique_assets), encoding="utf-8")

        probe_map: dict[str, dict] = {}
        stage_start = perf_counter()
        if unique_assets:
            progress("probe", 70, "Probing assets with httpx")
            self._run_httpx(
                tool_path=httpx.path,
                request=request,
                input_file=asset_urls_txt,
                out_file=httpx_jsonl,
            )
            probe_map = load_httpx_map(httpx_jsonl)
        else:
            httpx_jsonl.write_text("", encoding="utf-8")
        stage_durations["probe"] = perf_counter() - stage_start

        for row in deduped:
            probe = probe_map.get(row["asset_url"], {})
            row["status_code"] = probe.get("status_code")
            row["content_type"] = probe.get("content_type")
            row["content_length"] = probe.get("content_length")

        progress("db", 90, "Writing results to SQLite")
        stage_start = perf_counter()
        with connect(self.settings.db_path) as conn:
            replace_site_assets(
                conn=conn,
                site_url=base_site_url,
                scan_id=scan_id,
                rows=deduped,
            )
            summary = summary_for_site(conn, site_url=base_site_url)
        stage_durations["db"] = perf_counter() - stage_start
        stage_durations["total"] = perf_counter() - overall_start

        progress("done", 100, "Scan completed")
        return {
            "scan_id": scan_id,
            "site_url": base_site_url,
            "summary": summary,
            "stage_durations": stage_durations,
            "run_dir": str(run_dir),
            "counts": {
                "instances": len(deduped),
                "unique_assets": len(unique_assets),
            },
        }

    def _run_katana(self, *, tool_path: str, request: ScanRequest, out_file: Path) -> None:
        command = [
            tool_path,
            "-u",
            request.base_url,
            "-d",
            str(request.depth),
            "-j",
            "-silent",
            "-timeout",
            str(request.timeout_seconds),
            "-o",
            str(out_file),
            "-fs",
            "fqdn",
        ]
        if not request.follow_redirects:
            command.append("-dr")
        run_subprocess(command, label="katana")

    def _run_httpx(
        self, *, tool_path: str, request: ScanRequest, input_file: Path, out_file: Path
    ) -> None:
        command = [
            tool_path,
            "-l",
            str(input_file),
            "-j",
            "-silent",
            "-sc",
            "-ct",
            "-cl",
            "-timeout",
            str(request.timeout_seconds),
            "-o",
            str(out_file),
        ]
        if request.follow_redirects:
            command.append("-fr")
        run_subprocess(command, label="httpx")

    def _extract_instances(
        self,
        *,
        site_url: str,
        site_host: str,
        katana_jsonl: Path,
        robots: "RobotsGate",
        max_pages: int,
        selected_types: set[ResourceType] | None,
        include_pattern,
        exclude_pattern,
        discovered_at: datetime,
    ) -> list[dict]:
        rows: list[dict] = []
        seen_pages: set[str] = set()
        page_instances_seen: dict[str, set[str]] = defaultdict(set)

        with katana_jsonl.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                page_url = normalize_identity_url(extract_page_url(entry) or "")
                if not page_url:
                    continue
                if urlsplit(page_url).hostname != site_host:
                    continue
                if page_url not in seen_pages:
                    seen_pages.add(page_url)
                    if len(seen_pages) > max_pages:
                        break
                if not robots.is_allowed(page_url):
                    continue

                response = entry.get("response") or {}
                body = response.get("body")
                if not isinstance(body, str) or not body.strip():
                    continue
                if not is_html_response(response=response, body=body):
                    continue

                instances = extract_asset_instances(
                    site_url=site_url,
                    page_url=page_url,
                    html=body,
                    selected_types=selected_types,
                    include_pattern=include_pattern,
                    exclude_pattern=exclude_pattern,
                )

                for instance in instances:
                    if instance.instance_key in page_instances_seen[page_url]:
                        continue
                    page_instances_seen[page_url].add(instance.instance_key)
                    rows.append(
                        instance_to_row(
                            instance=instance,
                            discovered_at=discovered_at,
                        )
                    )
        return rows


def extract_page_url(entry: dict) -> str | None:
    request = entry.get("request") or {}
    if isinstance(request, dict):
        endpoint = request.get("endpoint")
        if isinstance(endpoint, str) and endpoint:
            return endpoint
    candidate = entry.get("url")
    if isinstance(candidate, str) and candidate:
        return candidate
    return None


def is_html_response(*, response: dict, body: str) -> bool:
    headers = response.get("headers") or {}
    content_type = ""
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() == "content-type":
                content_type = str(value).lower()
                break
    if "text/html" in content_type or "application/xhtml+xml" in content_type:
        return True
    return "<html" in body.lower() or "<!doctype html" in body.lower()


def instance_to_row(*, instance: AssetInstance, discovered_at: datetime) -> dict:
    return {
        **asdict(instance),
        "discovered_at": discovered_at.isoformat(),
    }


def dedupe_instances_by_key(rows: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        key = row["instance_key"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def load_httpx_map(httpx_jsonl: Path) -> dict[str, dict]:
    probe_map: dict[str, dict] = {}
    if not httpx_jsonl.exists():
        return probe_map
    with httpx_jsonl.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            candidates = []
            for key in ("input", "url"):
                value = row.get(key)
                if isinstance(value, str):
                    normalized = normalize_identity_url(value)
                    if normalized:
                        candidates.append(normalized)
            metadata = {
                "status_code": row.get("status_code"),
                "content_type": row.get("content_type"),
                "content_length": row.get("content_length"),
            }
            for candidate in candidates:
                probe_map[candidate] = metadata
    return probe_map


class RobotsGate:
    def __init__(self, base_url: str, enabled: bool):
        self.enabled = enabled
        self._parser: RobotFileParser | None = None
        if not enabled:
            return
        parsed = urlsplit(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.read()
        except Exception:
            self._parser = None
        else:
            self._parser = parser

    def is_allowed(self, url: str) -> bool:
        if not self.enabled:
            return True
        if self._parser is None:
            return True
        try:
            return self._parser.can_fetch("*", url)
        except Exception:
            return True


def run_subprocess(command: list[str], *, label: str) -> None:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        message = (
            f"{label} failed with exit {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
        raise RuntimeError(message)


def normalize_site_origin(url: str) -> str | None:
    normalized = normalize_identity_url(url)
    if not normalized:
        return None
    parts = urlsplit(normalized)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"
