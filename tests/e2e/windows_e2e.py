"""E2E no Windows: apply -> verify -> revert com Steam falsa.

Uso: python tests/e2e/windows_e2e.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core" / "src"))

from tdeck_core import manifest as mf, pck  # noqa: E402
from tdeck_core.catalog import validate_game  # noqa: E402
from tdeck_core.engines.godot import GodotPatcher  # noqa: E402
from tdeck_core.steam import GameInstall  # noqa: E402

APPID = 367520
PAYLOAD = b"PT_BR|ola mundo"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["TDECK_HOME"] = str(tmp / "state")

        game_dir = tmp / "Steam" / "steamapps" / "common" / "Fixture Game"
        game_dir.mkdir(parents=True)
        pack = game_dir / "Game.pck"
        pck.create_pack(pack, {
            "res://scenes/menu.tscn": b"scene-bytes",
            "res://locale/en.translation": b"EN|hello",
        })
        original = mf.sha256_file(pack)

        artifact = tmp / "pt.translation"
        artifact.write_bytes(PAYLOAD)

        game = validate_game({
            "appid": APPID, "name": "Fixture Game",
            "engine": {"kind": "godot", "version": "3.5"},
            "packs": ["Game.pck"], "buildids": {"tested": ["123456"]},
            "risk": {"anticheat": [], "online": False},
            "translations": [{
                "id": "fixture-ptbr", "appid": APPID, "locale": "pt_BR", "version": "1.0",
                "patch": {"kind": "godot_translation", "artifacts": [{
                    "type": "godot_translation", "url": "https://example.invalid/pt.translation",
                    "sha256": "c" * 64, "size": len(PAYLOAD),
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
        })
        install = GameInstall(appid=APPID, name=game.name, installdir="Fixture Game",
                              library=tmp / "Steam", buildid="123456", state_flags=4)
        translation = game.translations[0]

        print("[1/5] dry-run")
        plan = GodotPatcher.plan(install, game, translation, None, apply=False)
        assert plan.writes and mf.sha256_file(pack) == original
        print(json.dumps(plan.describe(), indent=2, ensure_ascii=False))

        print("[2/5] apply")
        result = GodotPatcher.apply(GodotPatcher.plan(install, game, translation, [artifact], True))
        assert result.ok, result.message
        info = pck.read_pack(pack)
        assert pck.extract(pack, "res://locale/en.translation", info) == PAYLOAD
        assert (game_dir / "override.cfg").is_file()
        assert mf.sha256_file(pack) != original

        print("[3/5] verify")
        assert GodotPatcher.verify(APPID, game_dir).status == mf.STATUS_INSTALLED

        print("[4/5] uninstall")
        assert GodotPatcher.uninstall(APPID, game_dir).ok
        assert not (game_dir / "override.cfg").exists()

        print("[5/5] hash byte-exato")
        restored = mf.sha256_file(pack)
        assert restored == original, f"{restored} != {original}"
        print(f"ok: {restored}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
