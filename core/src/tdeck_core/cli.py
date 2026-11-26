"""CLI do translate-deck."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__, manifest as mf
from .catalog import CatalogError, find_translation, load_catalog, validate_game, write_index
from .detect import detect
from .engines import PATCHERS  # noqa: F401  (registra os patchers)
from .pck import PckError, find_embedded_pack, read_pack
from .safety import SafetyError
from .sources.curated import CuratedSource
from .steam import SteamError, find_install, find_installs, steam_roots


def _print(data, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def _games(args):
    if getattr(args, "manual", None):
        from .sources.manual import load as load_manual
        game, translation, _ = load_manual(args.manual, args.appid, args.translation)
        return [game], translation
    if getattr(args, "index_url", None):
        games = CuratedSource(args.index_url, args.index_sha).load()
    elif getattr(args, "catalog", None):
        games = load_catalog(args.catalog)
    else:
        default = Path(os.environ.get("TDECK_CATALOG_DIR", Path.cwd() / "catalog"))
        games = load_catalog(default)
    if getattr(args, "appid", None) and getattr(args, "translation", None):
        _, translation = find_translation(games, args.appid, args.translation)
        return games, translation
    return games, None


def _game_dir(args) -> Path | None:
    if getattr(args, "game_dir", None):
        return Path(args.game_dir)
    install = find_install(args.appid, Path(args.steam_root) if getattr(args, "steam_root", None) else None)
    return install.path if install else None


def cmd_doctor(args) -> int:
    report = {
        "version": __version__,
        "python": sys.version.split()[0],
        "state_dir": str(mf.state_dir()),
        "steam_roots": [str(p) for p in steam_roots()],
        "installs": len(find_installs(Path(args.steam_root) if args.steam_root else None)),
        "godot_packs": shutil.which("gdre_tools") or os.environ.get("TDECK_GDRE_PATH") or "",
        "catalog_dir": str(args.catalog) if args.catalog else os.environ.get("TDECK_CATALOG_DIR", ""),
    }
    _print(report, args.json)
    print("ok", file=sys.stderr)
    return 0


def cmd_catalog_validate(args) -> int:
    games = load_catalog(args.catalog)
    _print({"games": len(games), "translations": sum(len(g.translations) for g in games)}, args.json)
    return 0


def cmd_catalog_index(args) -> int:
    index, digest_file = write_index(args.catalog, args.out)
    _print({"index": str(index), "sha256_file": str(digest_file),
            "sha256": digest_file.read_text(encoding="utf-8").strip()}, args.json)
    return 0


def cmd_games(args) -> int:
    installs = find_installs(Path(args.steam_root) if args.steam_root else None)
    games = []
    if getattr(args, "catalog", None) or getattr(args, "index_url", None) or getattr(args, "manual", None):
        try:
            games = _games(args)[0]
        except (CatalogError, OSError) as exc:
            print(f"aviso: catalogo ignorado ({exc})", file=sys.stderr)
    catalog = {game.appid: game for game in games}
    rows = []
    for install in installs:
        if catalog and install.appid not in catalog:
            continue
        game = catalog.get(install.appid)
        rows.append({
            "appid": install.appid,
            "name": install.name,
            "buildid": install.buildid,
            "path": str(install.path),
            "translations": [
                {"id": t.id, "locale": t.locale, "version": t.version,
                 "installable": t.installable, "blocked": t.blocked_reason}
                for t in (game.translations if game else [])
            ],
            "status": (mf.load(install.appid).translation_id if mf.load(install.appid) else ""),
        })
    _print({"games": rows}, args.json)
    return 0


def _prepare(args):
    install = find_install(args.appid, Path(args.steam_root) if args.steam_root else None)
    if install is None:
        raise SteamError(f"appid {args.appid} nao esta instalado")
    if not args.translation:
        raise CatalogError("informe --translation")
    if args.translation.startswith("local/"):
        from . import library
        scoped, game, translation, patcher, paths = library.load_target(
            install, args.appid, args.translation)
        return scoped, game, translation, patcher, paths
    games, translation = _games(args)
    if translation is None:
        raise CatalogError("informe --translation")
    game, translation = find_translation(games, args.appid, args.translation)
    if not translation.installable and not args.allow_unpermitted:
        raise CatalogError(
            f"traducao {translation.id!r} nao tem permissao registrada ({translation.blocked_reason}); "
            "use --allow-unpermitted apenas em fonte manual/sideload"
        )
    patcher = PATCHERS.get(game.engine.get("kind", ""))
    if patcher is None:
        raise CatalogError(f"engine {game.engine.get('kind')!r} ainda nao suportada")
    return install, game, translation, patcher, None


def cmd_plan(args) -> int:
    install, game, translation, patcher, paths = _prepare(args)
    plan = patcher.plan(install, game, translation, paths, apply=False)
    _print(plan.describe(), args.json)
    return 0


def cmd_install(args) -> int:
    install, game, translation, patcher, paths = _prepare(args)
    artifact_paths = paths
    if paths is None and args.apply:
        from . import download
        artifact_paths = [download.fetch(artifact.url, artifact.sha256)
                          for artifact in translation.artifacts]
    plan = patcher.plan(install, game, translation, artifact_paths, apply=args.apply)
    if not args.apply:
        _print(plan.describe(), args.json)
        print("dry-run: use --apply para gravar", file=sys.stderr)
        return 0
    result = patcher.apply(plan)
    _print({"plan": plan.describe(), "result": result.describe()}, args.json)
    return 0 if result.ok else 1


def cmd_library_list(args) -> int:
    from . import library
    entries = library.list_entries(args.appid)
    _print({"entries": [entry.to_dict() for entry in entries]}, args.json)
    return 0


def cmd_library_add(args) -> int:
    from . import library
    entry = library.add(args.appid, args.path, args.target or "")
    _print(entry.to_dict(), args.json)
    return 0


def cmd_library_remove(args) -> int:
    from . import library
    entry = library.remove(args.appid, args.id)
    _print({"removed": entry.to_dict()}, args.json)
    return 0


def cmd_inspect(args) -> int:
    from . import library
    _print(library.inspect(args.appid, args.path, args.target or ""), args.json)
    return 0


def cmd_uninstall(args) -> int:
    game_dir = _game_dir(args)
    if game_dir is None:
        raise SteamError(f"appid {args.appid} nao esta instalado")
    from .engines.godot import GodotPatcher
    result = GodotPatcher.uninstall(args.appid, game_dir)
    _print(result.describe(), args.json)
    return 0 if result.ok else 1


def cmd_verify(args) -> int:
    game_dir = _game_dir(args)
    current = mf.load(args.appid)
    if current is None:
        _print({"status": mf.STATUS_MISSING, "message": "nenhuma traducao instalada"}, args.json)
        return 1
    from .engines.godot import GodotPatcher
    result = GodotPatcher.verify(args.appid, game_dir) if game_dir else \
        type("R", (), {"describe": lambda self: {"status": "unknown"}, "ok": False})()
    _print(result.describe(), args.json)
    return 0 if result.ok else 1


def cmd_detect(args) -> int:
    game_dir = _game_dir(args)
    if game_dir is None:
        raise SteamError("informe --game-dir ou um appid instalado")
    _print({"path": str(game_dir), **detect(game_dir).__dict__}, args.json)
    return 0


def cmd_pck(args) -> int:
    embedded_at = None
    try:
        info = read_pack(args.file)
    except PckError as exc:
        embedded_at = find_embedded_pack(args.file)
        if embedded_at is None:
            _print({"ok": False, "error": str(exc)}, args.json)
            return 1
        info = read_pack(args.file, header_offset=embedded_at)
    entries = info.translation_entries if args.translations else info.entries
    payload = {
        "file": str(args.file),
        "layout": info.layout,
        "format_version": info.format_version,
        "engine": info.engine_str,
        "entries": len(info.entries),
        "listing": [{"path": e.norm_path, "size": e.size, "flags": e.flags} for e in entries],
    }
    if embedded_at is not None:
        payload["embedded_at"] = embedded_at
    _print(payload, args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", help="diretorio de estado (sobrepoe TDECK_HOME)")
    common.add_argument("--json", action="store_true", help="saida em JSON")

    parser = argparse.ArgumentParser(prog="tdeck", description="Hub de traducoes para Steam Deck",
                                     parents=[common])
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_catalog_opts(p, allow_manual=False):
        p.add_argument("--catalog", help="diretorio do catalogo local")
        p.add_argument("--index-url", help="URL https do index.json publicado")
        p.add_argument("--index-sha", help="sha256 fixado do indice")
        if allow_manual:
            p.add_argument("--manual", help="descritor JSON avulso (build sideload)")
            p.add_argument("--allow-unpermitted", action="store_true",
                           help="permite traducao sem permissao registrada (sideload)")

    p = sub.add_parser("doctor", help="checa ambiente", parents=[common])
    p.add_argument("--steam-root")
    p.add_argument("--catalog")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("catalog", help="valida e indexa o catalogo", parents=[common])
    cat = p.add_subparsers(dest="catalog_command", required=True)
    pv = cat.add_parser("validate", parents=[common])
    pv.add_argument("--catalog", required=True)
    pv.set_defaults(func=cmd_catalog_validate)
    pi = cat.add_parser("index", parents=[common])
    pi.add_argument("--catalog", required=True)
    pi.add_argument("--out")
    pi.set_defaults(func=cmd_catalog_index)

    p = sub.add_parser("games", help="lista jogos instalados", parents=[common])
    games_sub = p.add_subparsers(dest="games_command", required=True)
    pl = games_sub.add_parser("list", parents=[common])
    pl.add_argument("--steam-root")
    add_catalog_opts(pl)
    pl.set_defaults(func=cmd_games)

    p = sub.add_parser("library", help="biblioteca local de traducoes (sideload)",
                       parents=[common])
    lib = p.add_subparsers(dest="library_command", required=True)
    lib_list = lib.add_parser("list", parents=[common])
    lib_list.add_argument("--appid", type=int)
    lib_list.set_defaults(func=cmd_library_list)
    lib_add = lib.add_parser("add", parents=[common])
    lib_add.add_argument("path")
    lib_add.add_argument("--appid", type=int, required=True)
    lib_add.add_argument("--target", help="entrada do pack (res://...) quando ambigua")
    lib_add.set_defaults(func=cmd_library_add)
    lib_remove = lib.add_parser("remove", parents=[common])
    lib_remove.add_argument("appid", type=int)
    lib_remove.add_argument("id")
    lib_remove.set_defaults(func=cmd_library_remove)

    p = sub.add_parser("inspect", help="inspeciona um arquivo de traducao sem gravar",
                       parents=[common])
    p.add_argument("path")
    p.add_argument("--appid", type=int, required=True)
    p.add_argument("--target")
    p.set_defaults(func=cmd_inspect)

    for name, func, needs_target in (("plan", cmd_plan, True), ("install", cmd_install, True),
                                     ("uninstall", cmd_uninstall, False), ("verify", cmd_verify, False)):
        p = sub.add_parser(name, parents=[common])
        p.add_argument("--appid", type=int, required=True)
        p.add_argument("--steam-root")
        p.add_argument("--game-dir")
        if needs_target:
            p.add_argument("--translation")
            add_catalog_opts(p, allow_manual=True)
        if name == "install":
            p.add_argument("--apply", action="store_true", help="grava de verdade (padrao: dry-run)")
        p.set_defaults(func=func)

    p = sub.add_parser("detect", parents=[common])
    p.add_argument("--appid", type=int)
    p.add_argument("--game-dir")
    p.add_argument("--steam-root")
    p.set_defaults(func=cmd_detect)

    pck_parser = sub.add_parser("pck", help="inspeciona um .pck")
    pck_sub = pck_parser.add_subparsers(dest="pck_cmd", required=True)
    pck_list = pck_sub.add_parser("list", parents=[common], help="lista entradas do pack")
    pck_list.add_argument("--file", required=True)
    pck_list.add_argument("--translations", action="store_true",
                          help="mostra apenas .translation/.po")
    pck_list.set_defaults(func=cmd_pck)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.home:
        os.environ["TDECK_HOME"] = args.home
    try:
        return args.func(args)
    except (CatalogError, SteamError, SafetyError, OSError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        print(f"erro: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
