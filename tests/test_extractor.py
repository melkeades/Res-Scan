from __future__ import annotations

from app.extractor import extract_asset_instances, normalize_identity_url


def test_records_multiple_instances_for_same_asset_on_same_page() -> None:
    html = """
    <html>
      <body>
        <script src="/static/app.js"></script>
        <div><script src="/static/app.js"></script></div>
      </body>
    </html>
    """
    rows = extract_asset_instances(
        site_url="https://example.com",
        page_url="https://example.com/page",
        html=html,
    )
    scripts = [row for row in rows if row.asset_url.endswith("/static/app.js")]
    assert len(scripts) == 2
    assert scripts[0].dom_path != scripts[1].dom_path
    assert scripts[0].attr_occurrence == 1
    assert scripts[1].attr_occurrence == 2
    assert scripts[0].instance_key != scripts[1].instance_key


def test_normalize_identity_url_ignores_invalid_port_values() -> None:
    assert normalize_identity_url("https://example.com:blank/app.js") is None
