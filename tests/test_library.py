from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from tdeck_core import library, manifest as mf, pck
from tdeck_core.engines.godot import GodotPatcher
from tdeck_core.steam import GameInstall

APPID = 424242
TRANSLATION = b"PT_BR|ola mundo"


@pytest.fixture()
def install(tmp_path: Path, monkeypatch) -> GameInstall:
    monkeypatch.setenv("TDECK_HOME", str(tmp_path / "state"))
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
def artifact(tmp_path: Path) -> Path:
    path = tmp_path / "pt_BR.translation"
    path.write_bytes(TRANSLATION)
    return path


def test_add_build_and_install(install, artifact):
    entry = library.add(APPID, artifact, install=install)
    assert entry.ref.startswith("local/")
    assert entry.kind == "insert"
    assert entry.targets == ["res://locale/en.translation"]
    assert library.list_entries(APPID)[0].slug == entry.slug

    game, translation, paths = library.build(APPID, entry.ref)
    assert translation.patch_kind == "godot_translation"
    assert paths and paths[0].read_bytes() == TRANSLATION

    pack = install.path / "Game.pck"
    original = mf.sha256_file(pack)
    plan = GodotPatcher.plan(install, game, translation, paths, apply=True)
    assert GodotPatcher.apply(plan).ok
    assert GodotPatcher.verify(APPID, install.path).status == mf.STATUS_INSTALLED
    assert GodotPatcher.uninstall(APPID, install.path).ok
    assert mf.sha256_file(pack) == original


def test_add_same_file_is_idempotent(install, artifact):
    first = library.add(APPID, artifact, install=install)
    second = library.add(APPID, artifact, install=install)
    assert first.slug == second.slug
    assert len(library.list_entries(APPID)) == 1


def test_zip_translation(install, tmp_path):
    archive = tmp_path / "traducao.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("traducao/README.txt", "nota")
        handle.writestr("traducao/pt_BR.translation", TRANSLATION)
    entry = library.add(APPID, archive, install=install)
    assert entry.kind == "insert"
    assert library.build(APPID, entry.ref)[1].locale == "pt_BR"


def test_zip_slip_rejected(install, tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.translation", TRANSLATION)
    with pytest.raises(library.LibraryError, match="\\.\\."):
        library.add(APPID, archive, install=install)
    assert not (tmp_path / "escape.translation").exists()


def test_ambiguous_pack_requires_target(install, tmp_path):
    pck.create_pack(install.path / "Game.pck", {
        "res://locale/en.translation": b"EN|hello",
        "res://locale/es.translation": b"ES|hola",
    })
    artifact = tmp_path / "pt_BR.translation"
    artifact.write_bytes(TRANSLATION)
    report = library.inspect(APPID, artifact, install=install)
    assert report["ok"] and not report["target"]
    assert report["candidates"] == ["res://locale/en.translation", "res://locale/es.translation"]
    with pytest.raises(library.LibraryError, match="destino"):
        library.add(APPID, artifact, install=install)
    entry = library.add(APPID, artifact, "res://locale/es.translation", install=install)
    assert entry.targets == ["res://locale/es.translation"]


def test_pack_replace_apply_and_revert(install, tmp_path):
    translated = tmp_path / "Game.pck"
    pck.create_pack(translated, {
        "res://scenes/menu.tscn": b"scene-bytes",
        "res://locale/en.translation": TRANSLATION,
    })
    entry = library.add(APPID, translated, install=install)
    assert entry.kind == "replace_pack"

    game, translation, paths = library.build(APPID, entry.ref)
    assert translation.patch_kind == "godot_pack_replace"
    pack = install.path / "Game.pck"
    original = mf.sha256_file(pack)

    plan = GodotPatcher.plan(install, game, translation, paths, apply=True)
    assert GodotPatcher.apply(plan).ok
    assert pck.extract(pack, "res://locale/en.translation", pck.read_pack(pack)) == TRANSLATION
    assert GodotPatcher.verify(APPID, install.path).status == mf.STATUS_INSTALLED
    assert GodotPatcher.uninstall(APPID, install.path).ok
    assert mf.sha256_file(pack) == original


def test_remove_refuses_while_installed(install, artifact):
    entry = library.add(APPID, artifact, install=install)
    game, translation, paths = library.build(APPID, entry.ref)
    GodotPatcher.apply(GodotPatcher.plan(install, game, translation, paths, apply=True))
    with pytest.raises(library.LibraryError, match="reverta"):
        library.remove(APPID, entry.ref)
    GodotPatcher.uninstall(APPID, install.path)
    library.remove(APPID, entry.ref)
    assert library.list_entries(APPID) == []


def test_slug_format_and_po_artifact(install, tmp_path):
    artifact = tmp_path / "pt_BR.po"
    artifact.write_bytes(b'msgid "a"\nmsgstr "b"\n')
    entry = library.add(APPID, artifact, install=install)
    assert entry.slug == f"pt-br-{mf.sha256_file(artifact)[:8]}"
    game, translation, paths = library.build(APPID, entry.ref)
    assert translation.artifacts[0].type == "po"
    assert translation.patch_kind == "godot_translation"
    assert paths and paths[0].suffix == ".po"


def test_replace_required_bytes_includes_backup(install, tmp_path):
    translated = tmp_path / "Game.pck"
    pck.create_pack(translated, {"res://locale/en.translation": TRANSLATION})
    report = library.inspect(APPID, translated, install=install)
    assert report["mode"] == "replace_pack"
    pack_size = (install.path / "Game.pck").stat().st_size
    assert report["required_bytes"] == pack_size * 2 + translated.stat().st_size


def test_descriptor_buildid_warning(install, tmp_path):
    descriptor = tmp_path / "traducao.json"
    descriptor.write_text("""
    {
      "appid": 424242, "name": "Fixture Game",
      "engine": {"kind": "godot"},
      "packs": ["Game.pck"], "buildids": {"tested": ["999999"]},
      "risk": {"anticheat": [], "online": false},
      "translations": [{
        "id": "remote-ptbr", "appid": 424242, "locale": "pt_BR", "version": "1.0",
        "patch": {"kind": "godot_translation", "artifacts": [{
          "type": "godot_translation",
          "url": "https://example.invalid/pt.translation",
          "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "size": 12
        }]},
        "source": {"type": "manual", "author": "teste"},
        "permission": {"status": "unknown"},
        "install": {"method": "godot_pck_translations",
                    "params": {"insert": [{"pck_path": "res://locale/en.translation"}]}},
        "uninstall": {"method": "manifest_revert"},
        "files_touched": ["Game.pck"],
        "risk": {"requires_offline": true}
      }]
    }
    """, encoding="utf-8")
    report = library.inspect(APPID, descriptor, install=install)
    assert any("buildid 123456" in warning for warning in report["warnings"])
    pack_size = (install.path / "Game.pck").stat().st_size
    assert report["required_bytes"] == pack_size * 2 + 12


def test_descriptor_entry_keeps_remote_artifacts(install, tmp_path):
    descriptor = tmp_path / "traducao.json"
    descriptor.write_text("""
    {
      "appid": 424242, "name": "Fixture Game",
      "engine": {"kind": "godot"},
      "packs": ["Game.pck"], "buildids": {"tested": []},
      "risk": {"anticheat": [], "online": false},
      "translations": [{
        "id": "remote-ptbr", "appid": 424242, "locale": "pt_BR", "version": "1.0",
        "patch": {"kind": "godot_translation", "artifacts": [{
          "type": "godot_translation",
          "url": "https://example.invalid/pt.translation",
          "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "size": 12
        }]},
        "source": {"type": "manual", "author": "teste"},
        "permission": {"status": "granted",
                       "evidence_url": "https://example.invalid/termos",
                       "checked_at": "2026-11-26"},
        "install": {"method": "godot_pck_translations",
                    "params": {"insert": [{"pck_path": "res://locale/en.translation"}]}},
        "uninstall": {"method": "manifest_revert"},
        "files_touched": ["Game.pck"],
        "risk": {"requires_offline": true}
      }]
    }
    """, encoding="utf-8")
    entry = library.add(APPID, descriptor, install=install)
    assert entry.kind == "descriptor"
    game, translation, paths = library.build(APPID, entry.ref)
    assert paths is None
    assert translation.artifacts[0].url.startswith("https://")
