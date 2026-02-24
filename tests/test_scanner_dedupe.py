from __future__ import annotations

from app.scanner import dedupe_instances_by_key, normalize_site_origin


def test_exact_duplicate_instance_is_deduped_by_instance_key() -> None:
    row = {
        "site_url": "https://example.com",
        "page_url": "https://example.com/p",
        "asset_url": "https://example.com/a.js",
        "dom_path": "/html[1]/body[1]/script[1]",
        "asset_attr": "src",
        "attr_occurrence": 1,
        "instance_key": "abc",
        "resource_type": "js",
        "discovered_at": "2026-01-01T00:00:00+00:00",
    }
    deduped = dedupe_instances_by_key([row, dict(row)])
    assert len(deduped) == 1


def test_normalize_site_origin_is_host_based() -> None:
    assert normalize_site_origin("https://Example.com/path?a=1#x") == "https://example.com"
