"""Contrato comum entre engines e estrutura do plano de instalacao."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any


@dataclasses.dataclass
class InstallPlan:
    appid: int
    game_name: str
    game_dir: Path
    engine: str
    target: str
    translation_id: str
    locale: str
    version: str
    backups: list[str]
    created: list[str]
    writes: list[tuple[str, int]]
    required_bytes: int
    warnings: list[str] = dataclasses.field(default_factory=list)
    payload: Any = dataclasses.field(default=None, repr=False)

    def describe(self) -> dict:
        return {
            "appid": self.appid,
            "game": self.game_name,
            "engine": self.engine,
            "target": self.target,
            "translation": self.translation_id,
            "locale": self.locale,
            "version": self.version,
            "backups": self.backups,
            "created": self.created,
            "writes": [{"path": path, "size": size} for path, size in self.writes],
            "required_bytes": self.required_bytes,
            "warnings": self.warnings,
        }


@dataclasses.dataclass
class ApplyResult:
    ok: bool
    status: str
    message: str
    files: list[str] = dataclasses.field(default_factory=list)

    def describe(self) -> dict:
        return dataclasses.asdict(self)


PATCHERS: dict[str, type] = {}


def register(cls: type) -> type:
    PATCHERS[cls.kind] = cls
    return cls
