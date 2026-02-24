from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    init_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
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
            content_length INTEGER,
            scan_id TEXT NOT NULL,
            discovered_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_meta (
            site_url TEXT PRIMARY KEY,
            last_scan_id TEXT NOT NULL,
            last_scanned_at TEXT NOT NULL,
            last_status TEXT NOT NULL
        )
        """
    )
    conn.commit()


def replace_site_assets(
    conn: sqlite3.Connection,
    *,
    site_url: str,
    scan_id: str,
    rows: Sequence[dict],
) -> None:
    conn.execute("BEGIN")
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
            VALUES (?, ?, CURRENT_TIMESTAMP, 'done')
            ON CONFLICT(site_url) DO UPDATE
            SET last_scan_id = excluded.last_scan_id,
                last_scanned_at = excluded.last_scanned_at,
                last_status = excluded.last_status
            """,
            [site_url, scan_id],
        )
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def preview_assets(
    conn: sqlite3.Connection, *, site_url: str, limit: int, offset: int
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
    return [dict(row) for row in rows], int(total)


def summary_for_site(conn: sqlite3.Connection, *, site_url: str) -> dict:
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


def list_scanned_sites(conn: sqlite3.Connection) -> list[dict]:
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
    for row in rows:
        site_url = row["site_url"]
        parsed = urlsplit(site_url)
        response.append(
            {
                "site_url": site_url,
                "site_name": parsed.netloc or site_url,
                "resource_rows": int(row["resource_rows"]),
                "scanned_at": row["scanned_at"],
            }
        )
    return response


def assets_for_site(conn: sqlite3.Connection, *, site_url: str) -> tuple[list[dict], int]:
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
    return [dict(row) for row in rows], int(total)


def delete_site_data(conn: sqlite3.Connection, *, site_url: str) -> dict:
    conn.execute("BEGIN")
    try:
        removed_assets = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE site_url = ?", [site_url]
        ).fetchone()[0]
        removed_meta_rows = conn.execute(
            "SELECT COUNT(*) FROM scan_meta WHERE site_url = ?", [site_url]
        ).fetchone()[0]
        conn.execute("DELETE FROM assets WHERE site_url = ?", [site_url])
        conn.execute("DELETE FROM scan_meta WHERE site_url = ?", [site_url])
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    return {
        "site_url": site_url,
        "removed_assets": int(removed_assets),
        "removed_meta": bool(removed_meta_rows),
    }

