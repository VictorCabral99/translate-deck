"""E2E no Windows: apply/verify/revert (catalogo e biblioteca local) com Steam falsa.

Uso: python tests/e2e/windows_e2e.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core" / "src"))

from tdeck_core import cli, library, manifest as mf, pck  # noqa: E402
from tdeck_core.catalog import validate_game  # noqa: E402
from tdeck_core.engines.godot import GodotPatcher  # noqa: E402
from tdeck_core.steam import GameInstall  # noqa: E402

APPID = 367520
PAYLOAD = b"PT_BR|ola mundo"


def run_cli(argv: list[str]) -> int:
    print(f"$ tdeck {' '.join(argv)}")
    return cli.main(argv)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["TDECK_HOME"] = str(tmp / "state")
        os.environ["STEAM_ROOT"] = str(tmp / "Steam")

        game_dir = tmp / "Steam" / "steamapps" / "common" / "Fixture Game"
        game_dir.mkdir(parents=True)
        pack = game_dir / "Game.pck"
        pck.create_pack(pack, {
            "res://scenes/menu.tscn": b"scene-bytes",
            "res://locale/en.translation": b"EN|hello",
        })
        original = mf.sha256_file(pack)
        (tmp / "Steam" / "steamapps" / f"appmanifest_{APPID}.acf").write_text(
            '"AppState"\n{\n'
            f'  "appid" "{APPID}"\n'
            '  "name" "Fixture Game"\n'
            '  "installdir" "Fixture Game"\n'
            '  "buildid" "123456"\n'
            '  "StateFlags" "4"\n'
            '}\n',
            encoding="utf-8",
        )

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

        print("[1/9] dry-run do catalogo")
        plan = GodotPatcher.plan(install, game, translation, None, apply=False)
        assert plan.writes and mf.sha256_file(pack) == original
        print(json.dumps(plan.describe(), indent=2, ensure_ascii=False))

        print("[2/9] apply")
        result = GodotPatcher.apply(GodotPatcher.plan(install, game, translation, [artifact], True))
        assert result.ok, result.message
        info = pck.read_pack(pack)
        assert pck.extract(pack, "res://locale/en.translation", info) == PAYLOAD
        assert (game_dir / "override.cfg").is_file()
        assert mf.sha256_file(pack) != original

        print("[3/9] verify")
        assert GodotPatcher.verify(APPID, game_dir).status == mf.STATUS_INSTALLED

        print("[4/9] uninstall")
        assert GodotPatcher.uninstall(APPID, game_dir).ok
        assert not (game_dir / "override.cfg").exists()
        restored = mf.sha256_file(pack)
        assert restored == original, f"{restored} != {original}"

        print("[5/9] zip + inspect pela CLI")
        archive = tmp / "traducao.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("traducao/README.txt", "nota")
            handle.writestr("traducao/pt_BR.translation", PAYLOAD)
        assert run_cli(["inspect", str(archive), "--appid", str(APPID), "--json"]) == 0

        print("[6/9] library add + install local/<id> pela CLI")
        assert run_cli(["library", "add", str(archive), "--appid", str(APPID)]) == 0
        entries = library.list_entries(APPID)
        assert len(entries) == 1, entries
        local_ref = entries[0].ref
        assert run_cli(["install", "--appid", str(APPID), "--translation", local_ref,
                        "--apply", "--json"]) == 0
        assert pck.extract(pack, "res://locale/en.translation", pck.read_pack(pack)) == PAYLOAD
        assert run_cli(["verify", "--appid", str(APPID)]) == 0

        print("[7/9] revert local + remove da biblioteca")
        assert run_cli(["uninstall", "--appid", str(APPID)]) == 0
        assert mf.sha256_file(pack) == original
        assert run_cli(["library", "remove", str(APPID), local_ref]) == 0
        assert library.list_entries(APPID) == []

        print("[8/9] pack inteiro (replace) ate o revert")
        translated_pack = tmp / "Game.pck"
        pck.create_pack(translated_pack, {
            "res://scenes/menu.tscn": b"scene-bytes",
            "res://locale/en.translation": PAYLOAD,
        })
        assert run_cli(["library", "add", str(translated_pack), "--appid", str(APPID)]) == 0
        replace_ref = library.list_entries(APPID)[0].ref
        assert run_cli(["install", "--appid", str(APPID), "--translation", replace_ref,
                        "--apply", "--json"]) == 0
        assert pck.extract(pack, "res://locale/en.translation", pck.read_pack(pack)) == PAYLOAD
        assert GodotPatcher.verify(APPID, game_dir).status == mf.STATUS_INSTALLED
        assert run_cli(["uninstall", "--appid", str(APPID)]) == 0
        assert mf.sha256_file(pack) == original

        print("[9/9] biblioteca vazia e pack byte-exato")
        assert run_cli(["library", "remove", str(APPID), replace_ref]) == 0
        assert library.list_entries(APPID) == []
        print(f"ok: {original}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
