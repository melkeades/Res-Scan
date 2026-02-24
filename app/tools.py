from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class ToolResolutionError(RuntimeError):
    pass


@dataclass(slots=True)
class ResolvedTool:
    name: str
    path: str
    version: str


def resolve_and_validate_tool(name: str, configured_path: str | None = None) -> ResolvedTool:
    errors: list[str] = []
    for path in iter_candidate_paths(name=name, configured_path=configured_path):
        try:
            version = probe_version(path)
        except ToolResolutionError as exc:
            errors.append(f"{path}: {exc}")
            continue
        lower = version.lower()
        if "projectdiscovery.io" not in lower:
            errors.append(f"{path}: non-ProjectDiscovery binary")
            continue
        return ResolvedTool(name=name, path=path, version=extract_version(version))

    details = "\n".join(errors) if errors else "No executable candidates found."
    raise ToolResolutionError(f"Unable to validate '{name}'. Tried:\n{details}")


def iter_candidate_paths(name: str, configured_path: str | None = None) -> Iterable[str]:
    seen: set[str] = set()

    def push(path_value: str) -> str | None:
        normalized = str(Path(path_value).resolve())
        if normalized in seen:
            return None
        seen.add(normalized)
        if Path(normalized).exists():
            return normalized
        return None

    if configured_path:
        resolved = push(configured_path)
        if resolved:
            yield resolved

    go_bin = Path.home() / "go" / "bin" / f"{name}.exe"
    resolved = push(str(go_bin))
    if resolved:
        yield resolved

    which_path = shutil.which(name)
    if which_path:
        resolved = push(which_path)
        if resolved:
            yield resolved

    if shutil.which("where.exe"):
        completed = subprocess.run(
            ["where.exe", name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode == 0:
            for line in completed.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                resolved = push(line)
                if resolved:
                    yield resolved


def probe_version(path: str) -> str:
    try:
        completed = subprocess.run(
            [path, "-version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:  # pragma: no cover - covered via integration behavior
        raise ToolResolutionError(f"Failed to execute '{path} -version': {exc}") from exc
    return (completed.stdout or "") + (completed.stderr or "")


def extract_version(output: str) -> str:
    match = re.search(r"(?:Current\s+Version|Current\s+version):\s*([^\s]+)", output)
    if match:
        return match.group(1)
    return "unknown"
