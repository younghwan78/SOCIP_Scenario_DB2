"""Unit tests for the static-serving asset URL helper."""
from __future__ import annotations

import pytest

from dashboard.components import ui_theme

pytestmark = pytest.mark.unit


def test_returns_none_when_static_serving_disabled(monkeypatch, tmp_path):
    asset = tmp_path / "logo.png"
    asset.write_bytes(b"png")
    monkeypatch.setattr(ui_theme.st, "get_option", lambda _key: False)
    assert ui_theme.static_asset_url(asset) is None


def test_returns_none_for_missing_asset(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_theme.st, "get_option", lambda _key: True)
    assert ui_theme.static_asset_url(tmp_path / "missing.png") is None


def test_syncs_copy_and_builds_route(monkeypatch, tmp_path):
    asset = tmp_path / "Logo Test.png"
    asset.write_bytes(b"pngdata")
    static_dir = tmp_path / "static"
    monkeypatch.setattr(ui_theme, "SCENARIODB_STATIC_DIR", static_dir)
    monkeypatch.setattr(ui_theme.st, "get_option", lambda _key: True)

    url = ui_theme.static_asset_url(asset)

    assert url == "/app/static/logo_test.png"
    assert (static_dir / "logo_test.png").read_bytes() == b"pngdata"


def test_refreshes_stale_copy(monkeypatch, tmp_path):
    asset = tmp_path / "logo.png"
    asset.write_bytes(b"v1")
    static_dir = tmp_path / "static"
    monkeypatch.setattr(ui_theme, "SCENARIODB_STATIC_DIR", static_dir)
    monkeypatch.setattr(ui_theme.st, "get_option", lambda _key: True)

    ui_theme.static_asset_url(asset)
    asset.write_bytes(b"v2-longer")
    ui_theme.static_asset_url(asset)

    assert (static_dir / "logo.png").read_bytes() == b"v2-longer"
