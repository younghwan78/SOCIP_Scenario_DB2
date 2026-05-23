from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ASSET_DIR = ROOT / "dashboard" / "assets"


def test_scenariodb_logo_assets_are_packaged_with_dashboard() -> None:
    expected = {
        "ScenarioDB_DBexplorer.png",
        "ScenarioDB_EvidenceDashboard.png",
        "ScenarioDB_ExplorationWorkbench.png",
        "ScenarioDB_ImportWorkbench.png",
        "ScenarioDB_PipelineViewer.png",
        "ScenarioDB_sidebar logo.png",
    }

    assert expected <= {path.name for path in ASSET_DIR.glob("ScenarioDB_*.png")}


def test_sidebar_logo_is_applied_through_shared_theme() -> None:
    source = (ROOT / "dashboard" / "components" / "ui_theme.py").read_text(encoding="utf-8")

    assert "SCENARIODB_SIDEBAR_LOGO" in source
    assert "ScenarioDB_sidebar logo.png" in source
    assert "_asset_data_uri" in source
    assert "sdb-sidebar-brand" in source
    assert "inner.insertBefore(brand, inner.firstChild)" in source
    assert "brand.style.position = \"relative\"" in source
    assert "brand.style.margin = \"58px 14px 16px 14px\"" in source
    assert "brand.style.position = \"fixed\"" not in source
    assert "doc.body.appendChild(brand)" not in source
    assert "brand.style.top = \"74px\"" not in source
    assert "brand.style.width = \"260px\"" in source
    assert "brand.style.height = \"196px\"" in source
    assert "image.style.width = \"260px\"" in source
    assert "image.style.maxHeight = \"196px\"" in source
    assert "nativeToggle.style.top = \"54px\"" in source
    assert "const expandedPixels = parseInt(expandedWidth, 10) || 288" in source
    assert 'nativeToggle.style.left = `${expandedPixels - 46}px`' in source
    assert "nativeToggle.style.display = \"flex\"" in source
    assert "inner.style.setProperty(\"padding-top\", \"278px\", \"important\")" not in source


def test_home_tiles_render_each_menu_logo_above_title() -> None:
    source = (ROOT / "dashboard" / "Home.py").read_text(encoding="utf-8")

    for asset_name in [
        "ScenarioDB_DBexplorer.png",
        "ScenarioDB_PipelineViewer.png",
        "ScenarioDB_ImportWorkbench.png",
        "ScenarioDB_EvidenceDashboard.png",
        "ScenarioDB_ExplorationWorkbench.png",
    ]:
        assert asset_name in source
    assert "home-tile" in source
    assert "home-logo-panel" in source
    assert "home-tile-logo" in source
    assert "aspect-ratio: 1 / 1" in source
    assert "transform: scale(1.018)" in source
    assert "_asset_data_uri" in source
