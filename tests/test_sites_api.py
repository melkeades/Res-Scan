from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db import connect, replace_site_assets
from app.main import app, settings


def test_delete_site_api_removes_site(tmp_path) -> None:
    db_path = tmp_path / "assets.sqlite"
    old_db_path = settings.db_path
    settings.db_path = db_path
    try:
        with connect(db_path) as conn:
            replace_site_assets(
                conn,
                site_url="https://api.delete.test",
                scan_id="scan-api-del",
                rows=[
                    {
                        "site_url": "https://api.delete.test",
                        "page_url": "https://api.delete.test/p",
                        "asset_url": "https://api.delete.test/a.js",
                        "dom_path": "/html[1]/body[1]/script[1]",
                        "asset_attr": "src",
                        "attr_occurrence": 1,
                        "instance_key": "api-del-1",
                        "resource_type": "js",
                        "status_code": 200,
                        "content_type": "application/javascript",
                        "content_length": 1234,
                        "discovered_at": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            )

        client = TestClient(app)
        delete_res = client.delete(
            "/api/sites",
            params={"site_url": "https://api.delete.test"},
        )
        assert delete_res.status_code == 200
        payload = delete_res.json()
        assert payload["removed_assets"] == 1
        assert payload["removed_meta"] is True

        sites_res = client.get("/api/sites")
        assert sites_res.status_code == 200
        assert sites_res.json()["rows"] == []
    finally:
        settings.db_path = old_db_path
