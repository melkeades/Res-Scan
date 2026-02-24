from __future__ import annotations

from datetime import datetime, timezone

from app.db import assets_for_site, connect, list_scanned_sites, preview_assets, replace_site_assets


def _row(instance_key: str, page_url: str, asset_url: str, occurrence: int) -> dict:
    return {
        "site_url": "https://example.com",
        "page_url": page_url,
        "asset_url": asset_url,
        "dom_path": "/html[1]/body[1]/script[1]",
        "asset_attr": "src",
        "attr_occurrence": occurrence,
        "instance_key": instance_key,
        "resource_type": "js",
        "status_code": 200,
        "content_type": "application/javascript",
        "content_length": 1234,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
    }


def test_replace_site_assets_removes_stale_rows(tmp_path) -> None:
    db_path = tmp_path / "assets.duckdb"
    with connect(db_path) as conn:
        replace_site_assets(
            conn,
            site_url="https://example.com",
            scan_id="scan-1",
            rows=[
                _row("k1", "https://example.com/a", "https://example.com/one.js", 1),
                _row("k2", "https://example.com/a", "https://example.com/two.js", 1),
            ],
        )
        first_rows, first_total = preview_assets(
            conn, site_url="https://example.com", limit=100, offset=0
        )
        assert first_total == 2
        assert {r["instance_key"] for r in first_rows} == {"k1", "k2"}
        assert {"dom_path", "asset_attr", "attr_occurrence", "instance_key"} <= set(
            first_rows[0].keys()
        )

        replace_site_assets(
            conn,
            site_url="https://example.com",
            scan_id="scan-2",
            rows=[_row("k3", "https://example.com/a", "https://example.com/one.js", 1)],
        )
        second_rows, second_total = preview_assets(
            conn, site_url="https://example.com", limit=100, offset=0
        )
        assert second_total == 1
        assert second_rows[0]["instance_key"] == "k3"


def test_site_list_and_site_assets_views(tmp_path) -> None:
    db_path = tmp_path / "assets.duckdb"
    with connect(db_path) as conn:
        replace_site_assets(
            conn,
            site_url="https://example.com",
            scan_id="scan-a",
            rows=[_row("k1", "https://example.com/a", "https://example.com/one.js", 1)],
        )
        replace_site_assets(
            conn,
            site_url="https://demo.test",
            scan_id="scan-b",
            rows=[
                {
                    **_row("k2", "https://demo.test/a", "https://demo.test/two.js", 1),
                    "site_url": "https://demo.test",
                },
                {
                    **_row("k3", "https://demo.test/b", "https://demo.test/three.css", 1),
                    "site_url": "https://demo.test",
                },
            ],
        )

        sites = list_scanned_sites(conn)
        assert len(sites) == 2
        demo = [s for s in sites if s["site_url"] == "https://demo.test"][0]
        assert demo["site_name"] == "demo.test"
        assert demo["resource_rows"] == 2

        site_rows, total = assets_for_site(conn, site_url="https://demo.test")
        assert total == 2
        assert "site_url" not in site_rows[0]
        assert {"page_url", "asset_url", "dom_path", "discovered_at"} <= set(
            site_rows[0].keys()
        )
