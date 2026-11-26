"""Fonte manual (apenas build sideload): descritor JSON fornecido pelo usuario.

Este modulo e removido fisicamente do zip da loja pelo build; nada aqui roda
sem que o usuario aponte o arquivo/URL e confirme o hash exibido.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import download
from ..catalog import Game, Translation, validate_game


class ManualSourceError(Exception):
    pass


def read_descriptor(path_or_url: str) -> tuple[dict, str]:
    if path_or_url.startswith(("https://", "http://")):
        text = download.fetch_text(path_or_url)
    else:
        path = Path(path_or_url)
        if not path.is_file():
            raise ManualSourceError(f"descritor nao existe: {path}")
        text = path.read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManualSourceError(f"JSON invalido: {exc}") from exc
    return raw, text


def load(path_or_url: str, appid: int | None = None,
         translation_id: str | None = None) -> tuple[Game, Translation, dict]:
    raw, _ = read_descriptor(path_or_url)
    raw = dict(raw)
    raw["source"] = dict(raw.get("source") or {})
    raw["source"]["type"] = "manual"
    game = validate_game(raw, where="manual")
    if appid is not None and game.appid != appid:
        raise ManualSourceError(f"appid do descritor ({game.appid}) difere do pedido ({appid})")
    if translation_id:
        for translation in game.translations:
            if translation.id == translation_id:
                return game, translation, raw
        raise ManualSourceError(f"traducao {translation_id!r} ausente")
    if len(game.translations) != 1:
        raise ManualSourceError("descritor manual precisa ter exatamente uma traducao")
    return game, game.translations[0], raw
