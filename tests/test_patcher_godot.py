from __future__ import annotations

import os
from pathlib import Path

import pytest

from tdeck_core import manifest as mf, pck
from tdeck_core.catalog import validate_game
from tdeck_core.engines.godot import GodotError, GodotPatcher
from tdeck_core.steam import GameInstall

APPID = 367520
SHA = "b" * 64
TRANSLATION = b"PT_BR|ola mundo"


@pytest.fixture()
def steam_root(tmp_path: Path) -> Path:
    root = tmp_path / "Steam"
    game_dir = root / "steamapps" / "common" / "Fixture Game"
    game_dir.mkdir(parents=True)
    pck.create_pack(game_dir / "Game.pck", {
        "res://scenes/menu.tscn": b"scene-bytes",
        "res://locale/en.translation": b"EN|hello",
    })
    return root


@pytest.fixture()
def install(steam_root: Path) -> GameInstall:
    return GameInstall(appid=APPID, name="Fixture Game", installdir="Fixture Game",
                       library=steam_root, buildid="123456", state_flags=4)


@pytest.fixture()
def game():
    payload = {
        "appid": APPID, "name": "Fixture Game",
        "engine": {"kind": "godot", "version": "3.5"},
        "packs": ["Game.pck"],
        "buildids": {"tested": ["123456"]},
        "risk": {"anticheat": [], "online": False},
        "translations": [{
            "id": "fixture-ptbr", "appid": APPID, "locale": "pt_BR", "version": "1.0",
            "patch": {"kind": "godot_translation", "artifacts": [{
                "type": "godot_translation", "url": "https://example.invalid/pt.translation",
                "sha256": SHA, "size": len(TRANSLATION),
            }]},
            "source": {"type": "curated", "origin_url": "https://example.invalid/t",
                       "author": "Teste"},
            "permission": {"status": "granted", "evidence_url": "https://example.invalid/termos",
                           "excerpt": "livre para modificar", "checked_at": "2026-11-20"},
            "install": {"method": "godot_pck_translations", "params": {
                "insert": [{"pck_path": "res://locale/en.translation"}],
                "project_settings": {"internationalization/locale/fallback": "pt_BR"},
            }},
            "uninstall": {"method": "manifest_revert"},
            "files_touched": ["Game.pck", "override.cfg"],
            "risk": {"requires_offline": True},
        }],
    }
    return validate_game(payload)


@pytest.fixture()
def artifact(tmp_path: Path) -> Path:
    path = tmp_path / "pt.translation"
    path.write_bytes(TRANSLATION)
    return path


def test_dry_run_writes_nothing(install, game, monkeypatch, tmp_path):
    monkeypatch.setenv("TDECK_HOME", str(tmp_path / "state"))
    pack = install.path / "Game.pck"
    original = mf.sha256_file(pack)
    plan = GodotPatcher.plan(install, game, game.translations[0], None, apply=False)
    assert plan.writes
    assert mf.sha256_file(pack) == original
    assert mf.load(APPID) is None
    assert not (install.path / "override.cfg").exists()


def test_apply_verify_revert(install, game, artifact, monkeypatch, tmp_path):
    monkeypatch.setenv("TDECK_HOME", str(tmp_path / "state"))
    translation = game.translations[0]
    pack = install.path / "Game.pck"
    original = mf.sha256_file(pack)

    plan = GodotPatcher.plan(install, game, translation, [artifact], apply=True)
    result = GodotPatcher.apply(plan)
    assert result.ok, result.message

    info = pck.read_pack(pack)
    assert pck.extract(pack, "res://locale/en.translation", info) == TRANSLATION
    assert (install.path / "override.cfg").is_file()
    assert mf.load(APPID) is not None
    assert GodotPatcher.verify(APPID, install.path).status == mf.STATUS_INSTALLED

    removed = GodotPatcher.uninstall(APPID, install.path)
    assert removed.ok
    assert mf.sha256_file(pack) == original
    assert not (install.path / "override.cfg").exists()
    assert mf.load(APPID) is None


def test_verify_detects_steam_revalidation(install, game, artifact, monkeypatch, tmp_path):
    monkeypatch.setenv("TDECK_HOME", str(tmp_path / "state"))
    plan = GodotPatcher.plan(install, game, game.translations[0], [artifact], apply=True)
    GodotPatcher.apply(plan)

    original_data = {
        "res://scenes/menu.tscn": b"scene-bytes",
        "res://locale/en.translation": b"EN|hello",
    }
    pck.create_pack(install.path / "Game.pck", original_data)

    result = GodotPatcher.verify(APPID, install.path)
    assert result.status == mf.STATUS_REVALIDATED
    assert not result.ok


def test_refuses_anticheat(install, game, monkeypatch, tmp_path):
    monkeypatch.setenv("TDECK_HOME", str(tmp_path / "state"))
    (install.path / "EasyAntiCheat").mkdir()
    with pytest.raises(GodotError, match="anti-cheat"):
        GodotPatcher.plan(install, game, game.translations[0], None, apply=False)


def test_refuses_online_flagged_game(install, game, monkeypatch, tmp_path):
    monkeypatch.setenv("TDECK_HOME", str(tmp_path / "state"))
    game.risk["online"] = True
    with pytest.raises(GodotError, match="online"):
        GodotPatcher.plan(install, game, game.translations[0], None, apply=False)


def test_refuses_embedded_pck(tmp_path: Path):
    game_dir = tmp_path / "Embedded"
    game_dir.mkdir()
    pck.create_pack(game_dir / "Game.pck", {"res://a.txt": b"a"})
    payload = (game_dir / "Game.pck").read_bytes()
    (game_dir / "Game.pck").unlink()
    (game_dir / "game.exe").write_bytes(b"MZ" + b"\x00" * 16 + payload)
    with pytest.raises(GodotError, match="embutido"):
        GodotPatcher.resolve_pack(game_dir, {})


def test_more_than_one_pack_requires_catalog_hint(tmp_path: Path):
    game_dir = tmp_path / "Two"
    game_dir.mkdir()
    pck.create_pack(game_dir / "a.pck", {"res://a": b"a"})
    pck.create_pack(game_dir / "b.pck", {"res://b": b"b"})
    with pytest.raises(GodotError, match="mais de um"):
        GodotPatcher.resolve_pack(game_dir, {})
    assert GodotPatcher.resolve_pack(game_dir, {"pck": "b.pck"}).name == "b.pck"


def test_gdre_tool_requires_binary(install, game, monkeypatch, tmp_path):
    monkeypatch.setenv("TDECK_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("TDECK_GDRE_PATH", raising=False)
    monkeypatch.setattr("tdeck_core.engines.godot.shutil.which", lambda _name: None)
    game.translations[0].install["params"]["tool"] = "gdre"
    with pytest.raises(GodotError, match="GDRE"):
        GodotPatcher.plan(install, game, game.translations[0], None, apply=False)


@pytest.mark.skipif(not os.environ.get("TDECK_GDRE_PATH"),
                    reason="defina TDECK_GDRE_PATH para testar o GDRE real")
def test_apply_via_gdre(install, game, artifact, monkeypatch, tmp_path):
    monkeypatch.setenv("TDECK_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("TDECK_GDRE_PATH", os.environ["TDECK_GDRE_PATH"])
    game.translations[0].install["params"]["tool"] = "gdre"
    pack = install.path / "Game.pck"
    original = mf.sha256_file(pack)

    plan = GodotPatcher.plan(install, game, game.translations[0], [artifact], apply=True)
    assert plan.payload["tool"] == "gdre"
    result = GodotPatcher.apply(plan)
    assert result.ok, result.message
    info = pck.read_pack(pack)
    assert pck.extract(pack, "res://locale/en.translation", info) == TRANSLATION
    assert GodotPatcher.verify(APPID, install.path).status == mf.STATUS_INSTALLED

    assert GodotPatcher.uninstall(APPID, install.path).ok
    assert mf.sha256_file(pack) == original
