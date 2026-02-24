from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

import duckdb


def connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    init_schema(conn)
    return conn


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            site_url TEXT NOT NULL,
            page_url TEXT NOT NULL,
            asset_url TEXT NOT NULL,
            dom_path TEXT NOT NULL,
            asset_attr TEXT NOT NULL,
            attr_occurrence INTEGER NOT NULL,
            instance_key TEXT PRIMARY KEY,
            resource_type TEXT,
            status_code INTEGER,
            content_type TEXT,
            content_length BIGINT,
            scan_id TEXT NOT NULL,
            discovered_at TIMESTAMP NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_meta (
            site_url TEXT PRIMARY KEY,
            last_scan_id TEXT NOT NULL,
            last_scanned_at TIMESTAMP NOT NULL,
            last_status TEXT NOT NULL
        )
        """
    )


def replace_site_assets(
    conn: duckdb.DuckDBPyConnection,
    *,
    site_url: str,
    scan_id: str,
    rows: Sequence[dict],
) -> None:
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute("DELETE FROM assets WHERE site_url = ?", [site_url])
        if rows:
            conn.executemany(
                """
                INSERT INTO assets (
                    site_url,
                    page_url,
                    asset_url,
                    dom_path,
                    asset_attr,
                    attr_occurrence,
                    instance_key,
                    resource_type,
                    status_code,
                    content_type,
                    content_length,
                    scan_id,
                    discovered_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["site_url"],
                        row["page_url"],
                        row["asset_url"],
                        row["dom_path"],
                        row["asset_attr"],
                        row["attr_occurrence"],
                        row["instance_key"],
                        row.get("resource_type"),
                        row.get("status_code"),
                        row.get("content_type"),
                        row.get("content_length"),
                        scan_id,
                        row["discovered_at"],
                    )
                    for row in rows
                ],
            )

        conn.execute(
            """
            INSERT INTO scan_meta (site_url, last_scan_id, last_scanned_at, last_status)
            VALUES (?, ?, NOW(), 'done')
            ON CONFLICT(site_url) DO UPDATE
            SET last_scan_id = excluded.last_scan_id,
                last_scanned_at = excluded.last_scanned_at,
                last_status = excluded.last_status
            """,
            [site_url, scan_id],
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def preview_assets(
    conn: duckdb.DuckDBPyConnection, *, site_url: str, limit: int, offset: int
) -> tuple[list[dict], int]:
    rows = conn.execute(
        """
        SELECT
            site_url,
            page_url,
            asset_url,
            dom_path,
            asset_attr,
            attr_occurrence,
            instance_key,
            resource_type,
            status_code,
            content_type,
            content_length,
            scan_id,
            discovered_at
        FROM assets
        WHERE site_url = ?
        ORDER BY page_url, dom_path, asset_attr, attr_occurrence
        LIMIT ? OFFSET ?
        """,
        [site_url, limit, offset],
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM assets WHERE site_url = ?", [site_url]
    ).fetchone()[0]
    columns = [
        "site_url",
        "page_url",
        "asset_url",
        "dom_path",
        "asset_attr",
        "attr_occurrence",
        "instance_key",
        "resource_type",
        "status_code",
        "content_type",
        "content_length",
        "scan_id",
        "discovered_at",
    ]
    return [dict(zip(columns, row, strict=False)) for row in rows], int(total)


def summary_for_site(conn: duckdb.DuckDBPyConnection, *, site_url: str) -> dict:
    by_type_rows = conn.execute(
        """
        SELECT
            COALESCE(resource_type, 'unknown') AS resource_type,
            COUNT(*) AS instance_count,
            SUM(COALESCE(content_length, 0)) AS total_bytes
        FROM assets
        WHERE site_url = ?
        GROUP BY 1
        ORDER BY total_bytes DESC, instance_count DESC
        """,
        [site_url],
    ).fetchall()
    by_type = [
        {
            "resource_type": row[0],
            "instance_count": int(row[1]),
            "total_bytes": int(row[2] or 0),
        }
        for row in by_type_rows
    ]
    totals_row = conn.execute(
        """
        SELECT
            COUNT(*) AS instance_count,
            COUNT(DISTINCT asset_url) AS unique_assets,
            SUM(COALESCE(content_length, 0)) AS total_bytes
        FROM assets
        WHERE site_url = ?
        """,
        [site_url],
    ).fetchone()
    return {
        "by_type": by_type,
        "totals": {
            "instance_count": int(totals_row[0]),
            "unique_assets": int(totals_row[1]),
            "total_bytes": int(totals_row[2] or 0),
        },
    }


def list_scanned_sites(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            site_url,
            COUNT(*) AS resource_rows,
            MAX(discovered_at) AS scanned_at
        FROM assets
        GROUP BY site_url
        ORDER BY scanned_at DESC, site_url ASC
        """
    ).fetchall()
    response = []
    for site_url, resource_rows, scanned_at in rows:
        parsed = urlsplit(site_url)
        site_name = parsed.netloc or site_url
        response.append(
            {
                "site_url": site_url,
                "site_name": site_name,
                "resource_rows": int(resource_rows),
                "scanned_at": scanned_at,
            }
        )
    return response


def assets_for_site(conn: duckdb.DuckDBPyConnection, *, site_url: str) -> tuple[list[dict], int]:
    rows = conn.execute(
        """
        SELECT
            page_url,
            asset_url,
            dom_path,
            asset_attr,
            attr_occurrence,
            instance_key,
            resource_type,
            status_code,
            content_type,
            content_length,
            scan_id,
            discovered_at
        FROM assets
        WHERE site_url = ?
        """,
        [site_url],
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM assets WHERE site_url = ?", [site_url]
    ).fetchone()[0]
    columns = [
        "page_url",
        "asset_url",
        "dom_path",
        "asset_attr",
        "attr_occurrence",
        "instance_key",
        "resource_type",
        "status_code",
        "content_type",
        "content_length",
        "scan_id",
        "discovered_at",
    ]
    return [dict(zip(columns, row, strict=False)) for row in rows], int(total)
