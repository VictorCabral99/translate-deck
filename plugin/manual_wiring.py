"""Fonte manual (sideload). Este arquivo NAO entra no zip da loja."""

from __future__ import annotations

from tdeck_core import library
from tdeck_core.catalog import Game, Translation
from tdeck_core.engines import PATCHERS
from tdeck_core.sources.manual import load
from tdeck_core.steam import GameInstall


def load_target(install: GameInstall, appid: int, translation_id: str, path: str):
    game: Game
    game, translation, _ = load(path, appid, translation_id)
    if not translation.installable:
        raise RuntimeError(
            f"descritor manual sem permissao registrada ({translation.blocked_reason})"
        )
    patcher = PATCHERS.get(game.engine.get("kind", ""))
    if patcher is None:
        raise RuntimeError(f"engine {game.engine.get('kind')!r} nao suportada")
    return install, game, translation, patcher


def load_library_target(install: GameInstall, appid: int, translation_id: str):
    return library.load_target(install, appid, translation_id)


def inspect_translation(appid: int, path: str, target: str = "") -> dict:
    report = library.inspect(appid, path, target)
    return report


def library_add(appid: int, path: str, target: str = "") -> dict:
    return library.add(appid, path, target).to_dict()


def library_remove(appid: int, translation_id: str) -> dict:
    return library.remove(appid, translation_id).to_dict()


def library_list(appid: int | None = None) -> list[dict]:
    return [entry.to_dict() for entry in library.list_entries(appid)]
