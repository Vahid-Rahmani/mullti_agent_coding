from pathlib import Path

from scripts.core.taxonomy.build import write_taxonomy
from scripts.core.taxonomy.overrides import load_overrides


def test_rebuild_preserves_curated_overrides():
    before = load_overrides()
    artifact = write_taxonomy()
    assert artifact.is_file()
    assert load_overrides() == before


def test_dashboard_taxonomy_interface_uses_api_contract():
    root = Path.cwd()
    html = (root / "scripts" / "web_ui" / "static" / "index.html").read_text(encoding="utf-8")
    app = (root / "scripts" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'data-tab="taxonomy"' in html
    assert '"/api/taxonomy"' in app
    assert '"/api/taxonomy/rebuild"' in app
