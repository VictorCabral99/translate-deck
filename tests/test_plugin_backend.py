from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest

from tdeck_core import library, manifest as mf, pck
from tdeck_core.steam import GameInstall

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugin"
APPID = 515151


@pytest.fixture()
def backend(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TDECK_HOME", str(tmp_path / "state"))
    decky = types.ModuleType("decky")
    decky.DECKY_PLUGIN_DIR = str(PLUGIN_DIR)
    decky.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path / "runtime")
    decky.DECKY_PLUGIN_LOG_DIR = str(tmp_path / "log")
    decky.logger = logging.getLogger("decky-test")
    monkeypatch.setitem(sys.modules, "decky", decky)
    monkeypatch.syspath_prepend(str(PLUGIN_DIR))
    spec = importlib.util.spec_from_file_location("td_plugin_main", PLUGIN_DIR / "main.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def install(tmp_path: Path) -> GameInstall:
    root = tmp_path / "Steam"
    game_dir = root / "steamapps" / "common" / "Fixture Game"
    game_dir.mkdir(parents=True)
    pck.create_pack(game_dir / "Game.pck", {
        "res://scenes/menu.tscn": b"scene-bytes",
        "res://locale/en.translation": b"EN|hello",
    })
    return GameInstall(appid=APPID, name="Fixture Game", installdir="Fixture Game",
                       library=root, buildid="123456", state_flags=4)


@pytest.fixture()
def entry(install, tmp_path):
    artifact = tmp_path / "pt_BR.translation"
    artifact.write_bytes(b"PT_BR|ola")
    return library.add(APPID, artifact, install=install)


def test_rows_include_local_library(backend, install, entry, monkeypatch):
    rows = backend.Plugin._rows([install], {})
    assert rows[0]["engine"] == "godot"
    local = [t for t in rows[0]["translations"] if t["local"]]
    assert [t["id"] for t in local] == [entry.ref]
    assert local[0]["installable"]


def test_target_resolves_library(backend, install, entry, monkeypatch):
    monkeypatch.setattr(backend, "find_install", lambda appid: install)
    plugin = backend.Plugin()
    resolved, game, translation, patcher, paths = plugin._target(APPID, entry.ref, "")
    assert resolved is install
    assert translation.patch_kind == "godot_translation"
    assert paths and paths[0].is_file()
    result = asyncio.run(plugin.plan(APPID, entry.ref))
    assert result["ok"], result.get("error")
    assert [item["path"] for item in result["plan"]["writes"]] == ["res://locale/en.translation"]


def test_list_games_without_catalog_still_lists(backend, install, entry, monkeypatch):
    monkeypatch.setattr(backend, "find_installs", lambda: [install])

    def no_catalog():
        raise backend.cat.CatalogError("catalogo ausente")

    monkeypatch.setattr(backend, "_load_games", no_catalog)
    result = asyncio.run(backend.Plugin().list_games())
    assert result["ok"]
    assert result["warning"] == "catalogo ausente"
    assert result["games"][0]["translations"][0]["local"]


def test_store_edition_hides_library(backend, install, entry, monkeypatch):
    monkeypatch.setattr(backend, "_manual_module", lambda: None)
    monkeypatch.setattr(backend, "find_installs", lambda: [install])
    monkeypatch.setattr(backend, "_load_games", lambda: [])
    result = asyncio.run(backend.Plugin().list_games())
    assert result["games"][0]["translations"] == []
    removed = asyncio.run(backend.Plugin().library_remove(APPID, entry.ref))
    assert not removed["ok"]
