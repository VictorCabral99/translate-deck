"""Manifesto de instalacao, backup e restauracao byte-exata."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from .safety import SafetyError

STATUS_INSTALLED = "installed"
STATUS_REVALIDATED = "revalidated"
STATUS_MISSING = "missing"
STATUS_PARTIAL = "partial"


def state_dir() -> Path:
    override = os.environ.get("TDECK_HOME")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "tdeck"
    return Path.home() / ".local" / "share" / "tdeck"


def sha256_file(path: str | Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def write_atomic(path: str | Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tdeck-tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


@dataclasses.dataclass
class InstalledFile:
    relpath: str
    backup: str | None
    sha256_before: str | None
    sha256_after: str
    size: int


@dataclasses.dataclass
class Manifest:
    appid: int
    translation_id: str
    locale: str
    version: str
    engine: str
    buildid: str
    installed_at: str
    tool: str
    files: list[InstalledFile]
    created_files: list[str]

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def manifest_path(appid: int) -> Path:
    return state_dir() / "manifests" / f"{appid}.json"


def backup_dir(appid: int, buildid: str) -> Path:
    return state_dir() / "backups" / str(appid) / (buildid or "unknown")


def load(appid: int) -> Manifest | None:
    path = manifest_path(appid)
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["files"] = [InstalledFile(**item) for item in raw.get("files", [])]
    return Manifest(**raw)


def save(manifest: Manifest) -> None:
    write_atomic(manifest_path(manifest.appid),
                 json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False).encode("utf-8"))


def delete(appid: int) -> None:
    manifest_path(appid).unlink(missing_ok=True)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def backup_file(game_dir: Path, relpath: str, appid: int, buildid: str) -> Path:
    source = Path(game_dir) / relpath
    if not source.is_file():
        raise SafetyError(f"arquivo para backup nao existe: {source}")
    destination = backup_dir(appid, buildid) / relpath
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def restore(manifest: Manifest, game_dir: Path) -> list[str]:
    """Restaura os backups e remove arquivos criados pelo patch."""
    restored: list[str] = []
    for item in manifest.files:
        if item.backup:
            backup = Path(item.backup)
            if not backup.is_file():
                raise SafetyError(f"backup ausente: {backup}")
            target = Path(game_dir) / item.relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            restored.append(item.relpath)
    for relpath in manifest.created_files:
        target = Path(game_dir) / relpath
        if target.is_file():
            target.unlink()
            restored.append(relpath)
    return restored


def verify(manifest: Manifest, game_dir: Path) -> tuple[str, list[str]]:
    changed: list[str] = []
    for item in manifest.files:
        target = Path(game_dir) / item.relpath
        if not target.is_file():
            return STATUS_MISSING, [item.relpath]
        if sha256_file(target) != item.sha256_after:
            changed.append(item.relpath)
    if changed:
        return STATUS_REVALIDATED, changed
    return STATUS_INSTALLED, []


def prune_backups(keep_days: int = 30) -> list[Path]:
    cutoff = time.time() - keep_days * 86400
    removed: list[Path] = []
    root = state_dir() / "backups"
    if not root.is_dir():
        return removed
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()) and path.stat().st_mtime < cutoff:
            path.rmdir()
            removed.append(path)
    return removed
