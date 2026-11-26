"""Fonte curada: indice publicado (GitHub Pages) com hash fixado."""

from __future__ import annotations

import json
from pathlib import Path

from .. import CATALOG_SCHEMA_VERSION, download
from ..catalog import CatalogError, Game, load_catalog, validate_game

INDEX_FILE = "index.json"


class CuratedSource:
    def __init__(self, index_url: str, pinned_sha256: str | None = None):
        self.index_url = index_url
        self.pinned_sha256 = pinned_sha256

    def load(self) -> list[Game]:
        if not self.index_url.startswith("https://"):
            raise CatalogError("o indice curado precisa ser servido por https")
        text = download.fetch_text(self.index_url, self.pinned_sha256)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CatalogError(f"indice invalido: {exc}") from exc
        if payload.get("schema_version") != CATALOG_SCHEMA_VERSION:
            raise CatalogError(
                f"schema_version do indice {payload.get('schema_version')} "
                f"diferente do esperado {CATALOG_SCHEMA_VERSION}"
            )
        games: list[Game] = []
        for raw in payload.get("games") or []:
            games.append(validate_game(raw, where=f"index:appid={raw.get('appid')}"))
        games.sort(key=lambda g: g.name.casefold())
        return games


def load_dir(root: str | Path) -> list[Game]:
    return load_catalog(root)
