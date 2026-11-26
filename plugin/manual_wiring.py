"""Fonte manual (sideload). Este arquivo NAO entra no zip da loja."""

from __future__ import annotations

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
