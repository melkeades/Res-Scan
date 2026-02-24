from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.config import RESOURCE_TYPES, ResourceType

TAG_ATTRS: dict[str, tuple[str, ...]] = {
    "script": ("src",),
    "link": ("href",),
    "img": ("src", "srcset"),
    "source": ("src", "srcset"),
    "video": ("src", "poster"),
    "audio": ("src",),
    "track": ("src",),
    "iframe": ("src",),
    "embed": ("src",),
    "object": ("data",),
    "input": ("src",),
    "a": ("href",),
    "use": ("href", "xlink:href"),
}

EXTENSIONS: dict[ResourceType, tuple[str, ...]] = {
    "css": (".css",),
    "js": (".js", ".mjs"),
    "images": (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".svg",
        ".ico",
        ".bmp",
        ".avif",
    ),
    "fonts": (".woff", ".woff2", ".ttf", ".otf", ".eot"),
    "video": (".mp4", ".webm", ".m3u8", ".mpd", ".mov", ".avi", ".mp3", ".wav"),
    "docs": (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv"),
}


@dataclass(slots=True)
class AssetInstance:
    site_url: str
    page_url: str
    asset_url: str
    dom_path: str
    asset_attr: str
    attr_occurrence: int
    instance_key: str
    resource_type: str | None


def extract_asset_instances(
    *,
    site_url: str,
    page_url: str,
    html: str,
    selected_types: set[ResourceType] | None = None,
    include_pattern=None,
    exclude_pattern=None,
) -> list[AssetInstance]:
    soup = BeautifulSoup(html, "lxml")
    counter: dict[tuple[str, str], int] = defaultdict(int)
    instances: list[AssetInstance] = []

    for node in soup.find_all(True):
        if not isinstance(node, Tag):
            continue
        attrs = TAG_ATTRS.get(node.name, ())
        if not attrs:
            continue
        dom_path = build_dom_path(node)

        for attr_name in attrs:
            raw_value = node.attrs.get(attr_name)
            if raw_value is None:
                continue
            for candidate in parse_attribute_urls(attr_name, raw_value):
                normalized = normalize_identity_url(urljoin(page_url, candidate))
                if not normalized:
                    continue
                if include_pattern and not include_pattern.search(normalized):
                    continue
                if exclude_pattern and exclude_pattern.search(normalized):
                    continue
                resource_type = classify_resource_type(
                    url=normalized, tag=node.name, attr=attr_name, node=node
                )
                if selected_types is not None and resource_type not in selected_types:
                    continue
                occurrence_key = (attr_name, normalized)
                counter[occurrence_key] += 1
                attr_occurrence = counter[occurrence_key]
                instance_key = make_instance_key(
                    site_url=site_url,
                    page_url=page_url,
                    asset_url=normalized,
                    dom_path=dom_path,
                    asset_attr=attr_name,
                    attr_occurrence=attr_occurrence,
                )
                instances.append(
                    AssetInstance(
                        site_url=site_url,
                        page_url=page_url,
                        asset_url=normalized,
                        dom_path=dom_path,
                        asset_attr=attr_name,
                        attr_occurrence=attr_occurrence,
                        instance_key=instance_key,
                        resource_type=resource_type,
                    )
                )

    return instances


def build_dom_path(node: Tag) -> str:
    segments: list[str] = []
    current = node
    while isinstance(current, Tag):
        index = 1
        sibling = current.previous_sibling
        while sibling is not None:
            if isinstance(sibling, Tag) and sibling.name == current.name:
                index += 1
            sibling = sibling.previous_sibling
        segments.append(f"{current.name}[{index}]")
        current = current.parent  # type: ignore[assignment]
    segments.reverse()
    return "/" + "/".join(segments)


def parse_attribute_urls(attr_name: str, raw_value) -> Iterable[str]:
    if isinstance(raw_value, list):
        for item in raw_value:
            yield from parse_attribute_urls(attr_name, item)
        return

    if not isinstance(raw_value, str):
        return

    if attr_name == "srcset":
        for entry in raw_value.split(","):
            entry = entry.strip()
            if not entry:
                continue
            url_part = entry.split(" ", 1)[0].strip()
            if url_part:
                yield url_part
        return

    candidate = raw_value.strip()
    if candidate:
        yield candidate


def normalize_identity_url(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"}:
        return None
    try:
        host = parts.hostname.lower() if parts.hostname else ""
    except ValueError:
        return None
    if not host:
        return None

    netloc = host
    try:
        port = parts.port
    except ValueError:
        return None
    if port:
        netloc = f"{netloc}:{port}"
    path = parts.path or "/"
    normalized = urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))

    if normalized.startswith(("http://", "https://")):
        return normalized
    return None


def classify_resource_type(url: str, tag: str, attr: str, node: Tag) -> ResourceType:
    lowered = urlsplit(url).path.lower()
    for resource_type, suffixes in EXTENSIONS.items():
        if lowered.endswith(suffixes):
            return resource_type

    if tag == "script" and attr == "src":
        return "js"
    if tag == "img":
        return "images"
    if tag == "video":
        return "video"
    if tag == "audio":
        return "video"
    if tag == "track":
        return "video"
    if tag == "link" and attr == "href":
        rel_values = node.attrs.get("rel", [])
        if isinstance(rel_values, str):
            rel_values = [rel_values]
        rel_values = [str(item).lower() for item in rel_values]
        if "stylesheet" in rel_values:
            return "css"
        if {"preload", "prefetch", "modulepreload"} & set(rel_values):
            as_value = str(node.attrs.get("as", "")).lower()
            if as_value in {"script"}:
                return "js"
            if as_value in {"style"}:
                return "css"
            if as_value in {"font"}:
                return "fonts"
            if as_value in {"image"}:
                return "images"
        if "icon" in rel_values:
            return "images"

    return "docs" if "docs" in RESOURCE_TYPES else "images"


def make_instance_key(
    *,
    site_url: str,
    page_url: str,
    asset_url: str,
    dom_path: str,
    asset_attr: str,
    attr_occurrence: int,
) -> str:
    material = "|".join(
        [
            site_url,
            page_url,
            asset_url,
            dom_path,
            asset_attr,
            str(attr_occurrence),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
