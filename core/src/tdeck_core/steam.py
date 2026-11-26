"""Descoberta de instalacoes da Steam (libraryfolders.vdf + appmanifest .acf)."""

from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path

STATE_FULLY_INSTALLED = 4


class SteamError(Exception):
    pass


@dataclasses.dataclass
class GameInstall:
    appid: int
    name: str
    installdir: str
    library: Path
    buildid: str
    state_flags: int

    @property
    def path(self) -> Path:
        return self.library / "steamapps" / "common" / self.installdir

    @property
    def installed(self) -> bool:
        return bool(self.state_flags & STATE_FULLY_INSTALLED) and self.path.is_dir()

    @property
    def compatdata(self) -> Path:
        return self.library / "steamapps" / "compatdata" / str(self.appid)

    @property
    def proton_prefix(self) -> Path | None:
        prefix = self.compatdata / "pfx"
        return prefix if prefix.is_dir() else None


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in "{}":
            tokens.append(ch)
            i += 1
        elif ch == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    i += 1
                buf.append(text[i])
                i += 1
            tokens.append("".join(buf))
            i += 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in '{}"':
                i += 1
            tokens.append(text[start:i])
    return tokens


def parse_vdf(text: str) -> dict:
    tokens = _tokenize(text)
    pos = 0

    def parse_block() -> dict:
        nonlocal pos
        block: dict = {}
        while pos < len(tokens):
            key = tokens[pos]
            pos += 1
            if key == "}":
                return block
            if pos >= len(tokens):
                break
            if tokens[pos] == "{":
                pos += 1
                block[key] = parse_block()
            else:
                block[key] = tokens[pos]
                pos += 1
        return block

    root: dict = {}
    while pos < len(tokens):
        key = tokens[pos]
        pos += 1
        if pos < len(tokens) and tokens[pos] == "{":
            pos += 1
            root[key] = parse_block()
        elif pos < len(tokens):
            root[key] = tokens[pos]
            pos += 1
    return root


def steam_roots() -> list[Path]:
    override = os.environ.get("STEAM_ROOT")
    if override:
        return [Path(override)]
    candidates: list[Path] = []
    home = Path.home()
    for rel in (".steam/steam", ".steam/root", ".local/share/Steam",
                "Library/Application Support/Steam"):
        candidates.append(home / rel)
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Steam")
    seen: list[Path] = []
    for candidate in candidates:
        if candidate not in seen and (candidate / "steamapps").is_dir():
            seen.append(candidate)
    return seen


def library_folders(root: Path) -> list[Path]:
    vdf = root / "steamapps" / "libraryfolders.vdf"
    libraries = [root]
    if not vdf.is_file():
        return libraries
    try:
        data = parse_vdf(vdf.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return libraries
    folders = data.get("libraryfolders", {})
    if isinstance(folders, dict):
        for value in folders.values():
            if isinstance(value, dict):
                path = value.get("path")
            else:
                path = value
            if isinstance(path, str) and path:
                candidate = Path(path)
                if candidate not in libraries and (candidate / "steamapps").is_dir():
                    libraries.append(candidate)
    return libraries


def _parse_acf(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    data = parse_vdf(text)
    return data.get("AppState", data)


def find_installs(steam_root: Path | None = None) -> list[GameInstall]:
    roots = [steam_root] if steam_root else steam_roots()
    installs: dict[int, GameInstall] = {}
    for root in roots:
        for library in library_folders(root):
            for acf in sorted((library / "steamapps").glob("appmanifest_*.acf")):
                try:
                    state = _parse_acf(acf)
                    appid = int(state.get("appid", 0))
                    installdir = sanitize_installdir(str(state.get("installdir", "")))
                    if not appid or not installdir:
                        continue
                    install = GameInstall(
                        appid=appid,
                        name=str(state.get("name", installdir)),
                        installdir=installdir,
                        library=library,
                        buildid=str(state.get("buildid", "")),
                        state_flags=int(state.get("StateFlags", 0)),
                    )
                    if install.installed:
                        installs.setdefault(appid, install)
                except (ValueError, OSError, SteamError):
                    continue
    return sorted(installs.values(), key=lambda g: g.name.casefold())


def find_install(appid: int, steam_root: Path | None = None) -> GameInstall | None:
    for install in find_installs(steam_root):
        if install.appid == appid:
            return install
    return None


def sanitize_installdir(value: str) -> str:
    if not re.fullmatch(r"[^\\/:*?\"<>|\x00]+", value or ""):
        raise SteamError(f"installdir suspeita: {value!r}")
    if value.strip(". ") == "" or len(value) > 200:
        raise SteamError(f"installdir suspeita: {value!r}")
    return value
