from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tdeck_core.catalog import (
    CatalogError, build_index, find_translation, load_catalog, validate_game, write_index,
)

SHA = "a" * 64


def game_payload(**overrides) -> dict:
    payload = {
        "appid": 367520,
        "name": "Hollow Knight",
        "engine": {"kind": "godot", "version": "3.5"},
        "packs": ["Game.pck"],
        "buildids": {"tested": ["123456"], "min": "120000"},
        "risk": {"anticheat": [], "online": False},
        "notes": "",
        "translations": [{
            "id": "hk-ptbr-gamevicio-1.0",
            "title": "PT-BR GameVicio",
            "appid": 367520,
            "locale": "pt_BR",
            "version": "1.0",
            "patch": {"kind": "godot_translation", "artifacts": [{
                "type": "godot_translation",
                "url": "https://example.invalid/pt_BR.translation",
                "sha256": SHA,
                "size": 1024,
            }]},
            "source": {"type": "curated", "author": "Fulano",
                       "origin_url": "https://gamevicio.com/x"},
            "permission": {"status": "granted", "evidence_url": "https://gamevicio.com/termos",
                           "excerpt": "livres para baixar, modificar", "checked_at": "2026-11-20"},
            "install": {"method": "godot_pck_translations",
                        "params": {"insert": [{"pck_path": "res://locale/pt_BR.translation"}]}},
            "uninstall": {"method": "manifest_revert"},
            "files_touched": ["Game.pck"],
            "risk": {"requires_offline": True},
        }],
    }
    payload.update(overrides)
    return payload


def test_valid_game():
    game = validate_game(game_payload())
    assert game.appid == 367520
    assert game.translations[0].installable


def test_granted_requires_evidence():
    payload = game_payload()
    payload["translations"][0]["permission"] = {"status": "granted"}
    with pytest.raises(CatalogError, match="evidence_url"):
        validate_game(payload)


def test_unknown_permission_is_not_installable():
    payload = game_payload()
    payload["translations"][0]["permission"] = {"status": "unknown"}
    game = validate_game(payload)
    assert not game.translations[0].installable
    assert "unknown" in game.translations[0].blocked_reason


def test_forbidden_script_key():
    payload = game_payload()
    payload["translations"][0]["install"]["params"]["script"] = "rm -rf /"
    with pytest.raises(CatalogError, match="proibida"):
        validate_game(payload)


def test_sha256_must_be_hex():
    payload = game_payload()
    payload["translations"][0]["patch"]["artifacts"][0]["sha256"] = "zz"
    with pytest.raises(CatalogError, match="sha256"):
        validate_game(payload)


def test_anticheat_must_be_known():
    payload = game_payload(risk={"anticheat": ["nope"], "online": False})
    with pytest.raises(CatalogError, match="anticheat"):
        validate_game(payload)


def test_load_and_index_are_deterministic(tmp_path: Path):
    catalog_dir = tmp_path / "catalog"
    (catalog_dir / "games").mkdir(parents=True)
    (catalog_dir / "games" / "367520.json").write_text(
        json.dumps(game_payload(), ensure_ascii=False), encoding="utf-8")
    games = load_catalog(catalog_dir)
    assert len(games) == 1

    first = json.dumps(build_index(games), sort_keys=True, ensure_ascii=False)
    second = json.dumps(build_index(games), sort_keys=True, ensure_ascii=False)
    assert first == second

    index_path, digest_path = write_index(catalog_dir, tmp_path / "out")
    digest = hashlib.sha256(index_path.read_bytes()).hexdigest()
    assert digest_path.read_text(encoding="utf-8").strip() == digest


def test_pack_replace_kind_is_valid():
    payload = game_payload()
    translation = payload["translations"][0]
    translation["patch"] = {"kind": "godot_pack_replace", "artifacts": [{
        "type": "pck", "url": "https://example.invalid/Game.pck",
        "sha256": SHA, "size": 2048,
    }]}
    translation["install"] = {"method": "godot_pck_replace",
                              "params": {"replace_pack": True}}
    game = validate_game(payload)
    assert game.translations[0].patch_kind == "godot_pack_replace"
    index = build_index([game])
    install = index["games"][0]["translations"][0]["install"]
    assert install["params"]["replace_pack"] is True
    assert index["games"][0]["translations"][0]["patch"]["artifacts"][0]["type"] == "pck"


def test_unknown_install_method_rejected():
    payload = game_payload()
    payload["translations"][0]["install"]["method"] = "run_script"
    with pytest.raises(CatalogError, match="install.method"):
        validate_game(payload)


def test_duplicate_appid_and_id(tmp_path: Path):
    catalog_dir = tmp_path / "catalog"
    (catalog_dir / "games").mkdir(parents=True)
    (catalog_dir / "games" / "a.json").write_text(json.dumps(game_payload()), encoding="utf-8")
    (catalog_dir / "games" / "b.json").write_text(json.dumps(game_payload()), encoding="utf-8")
    with pytest.raises(CatalogError, match="appid duplicado"):
        load_catalog(catalog_dir)

    duplicated = game_payload()
    duplicated["translations"].append(dict(duplicated["translations"][0]))
    with pytest.raises(CatalogError, match="duplicado"):
        validate_game(duplicated)


def test_find_translation():
    game = validate_game(game_payload())
    found_game, translation = find_translation([game], 367520, "hk-ptbr-gamevicio-1.0")
    assert found_game is game and translation.locale == "pt_BR"
    with pytest.raises(CatalogError):
        find_translation([game], 367520, "nope")


def test_index_roundtrip():
    from tdeck_core.catalog import validate_index
    game = validate_game(game_payload())
    index = build_index([game])
    games = validate_index(index)
    assert [g.appid for g in games] == [367520]
    assert games[0].translations[0].installable
    with pytest.raises(CatalogError, match="schema_version"):
        validate_index({"schema_version": 999, "games": []})
