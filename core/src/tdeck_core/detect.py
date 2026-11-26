"""Deteccao de engine e de anti-cheat a partir dos arquivos da instalacao."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

ANTICHEAT_FILES = {
    "easyanticheat": "eac",
    "easyanticheat_eos": "eac",
    "easyanticheat_setup": "eac",
    "battleye": "battleye",
    "beservice": "battleye",
    "start_protected_game": "eac",
}
ANTICHEAT_SUFFIXES = ("_eac.exe", "_be.exe")
SKIP_DIRS = {"__pycache__", "node_modules"}


@dataclasses.dataclass
class Detection:
    engine: str
    anticheat: list[str]
    evidence: list[str]
    scanned: int


def _iter_files(root: Path, max_depth: int = 3, limit: int = 40_000):
    root = root.resolve()
    count = 0
    for current, dirs, files in os.walk(root):
        depth = len(Path(current).relative_to(root).parts)
        if depth >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d.casefold() not in SKIP_DIRS]
        for name in files:
            yield Path(current) / name
            count += 1
            if count >= limit:
                return


def detect_anticheat(game_dir: Path) -> tuple[list[str], list[str]]:
    found: set[str] = set()
    evidence: list[str] = []
    for current, dirs, _files in os.walk(game_dir.resolve()):
        for dirname in dirs:
            key = dirname.casefold()
            if key in ANTICHEAT_FILES:
                found.add(ANTICHEAT_FILES[key])
                evidence.append(str(Path(current, dirname).relative_to(game_dir)))
    for path in _iter_files(game_dir, max_depth=4):
        stem = path.stem.casefold()
        name = path.name.casefold()
        for key, kind in ANTICHEAT_FILES.items():
            if stem == key or name.startswith(key):
                found.add(kind)
                evidence.append(str(path.relative_to(game_dir)))
        if name.endswith(ANTICHEAT_SUFFIXES):
            found.add("eac")
            evidence.append(str(path.relative_to(game_dir)))
    return sorted(found), evidence[:10]


def detect_engine(game_dir: Path) -> tuple[str, list[str]]:
    game_dir = Path(game_dir)
    if not game_dir.is_dir():
        return "unknown", ["diretorio inexistente"]
    top = {p.name.casefold() for p in game_dir.iterdir() if p.is_file()}
    names = {p.name.casefold() for p in game_dir.iterdir()}
    evidence: list[str] = []

    if any(n.endswith(".pck") for n in names):
        evidence.append("arquivo .pck")
    if (game_dir / "UnityPlayer.dll").exists() or any(n.endswith("_data") and (game_dir / n).is_dir() for n in names):
        return "unity", evidence + ["UnityPlayer/_Data"]
    if (game_dir / "game" / "tl").is_dir() or (game_dir / "renpy").is_dir():
        return "renpy", evidence + ["renpy/"]
    if any(n.endswith(".pak") for n in names) or (game_dir / "Binaries" / "Win64").is_dir():
        return "unreal", evidence + [".pak/Binaries"]
    if (game_dir / "www" / "data").is_dir() or "game.rpgproject" in top:
        return "rpgmaker", evidence + ["www/data"]
    if "data.win" in top:
        return "gamemaker", evidence + ["data.win"]
    if evidence:
        return "godot", evidence
    return "unknown", []


def detect(game_dir: Path) -> Detection:
    engine, evidence = detect_engine(game_dir)
    anticheat, ac_evidence = detect_anticheat(game_dir)
    scanned = sum(1 for _ in _iter_files(game_dir, max_depth=3, limit=5000))
    return Detection(engine, anticheat, evidence + ac_evidence, scanned)
