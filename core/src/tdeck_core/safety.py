"""Travas, espaco em disco e verificacoes antes de tocar no jogo."""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import time
from pathlib import Path

STALE_SECONDS = 600


class SafetyError(Exception):
    pass


class LockError(SafetyError):
    pass


class Lock:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._fd: int | None = None

    def acquire(self) -> "Lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - self.path.stat().st_mtime
            except FileNotFoundError:
                age = 0
            if age > STALE_SECONDS:
                self.path.unlink(missing_ok=True)
                return self.acquire()
            raise LockError(f"outra operacao em andamento ({self.path})")
        with os.fdopen(self._fd, "w", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()} {int(time.time())}\n")
        return self

    def release(self) -> None:
        self.path.unlink(missing_ok=True)

    def __enter__(self) -> "Lock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()


def disk_free(path: Path) -> int:
    return shutil.disk_usage(str(path)).free


def check_space(path: Path, needed: int) -> None:
    free = disk_free(path)
    if free < needed:
        raise SafetyError(
            f"espaco insuficiente em {path}: precisa {needed // (1024 * 1024)} MB, "
            f"livre {free // (1024 * 1024)} MB"
        )


def processes_running(names: list[str]) -> list[str]:
    if not names:
        return []
    lowered = {n.casefold() for n in names}
    try:
        if os.name == "nt":
            output = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True,
                                    text=True, timeout=8).stdout
            listing = [line.split(",")[0].strip('"') for line in output.splitlines() if line]
        else:
            output = subprocess.run(["ps", "-eo", "comm="], capture_output=True,
                                    text=True, timeout=8).stdout
            listing = [line.strip() for line in output.splitlines() if line]
    except (OSError, subprocess.SubprocessError):
        return []
    return [name for name in listing if name.casefold() in lowered]


@dataclasses.dataclass
class Preflight:
    ok: bool
    errors: list[str]
    warnings: list[str]

    @property
    def summary(self) -> str:
        return "; ".join(self.errors) if self.errors else "ok"


def preflight(game_dir: Path, expected_engine: str, detected_engine: str,
              anticheat: list[str], needed_bytes: int,
              running: list[str] | None = None) -> Preflight:
    errors: list[str] = []
    warnings: list[str] = []
    if detected_engine != expected_engine:
        errors.append(f"engine detectada {detected_engine!r} difere do catalogo {expected_engine!r}")
    if anticheat:
        errors.append("anti-cheat detectado: " + ", ".join(anticheat))
    if running:
        errors.append("jogo em execucao: " + ", ".join(running))
    if needed_bytes:
        try:
            check_space(game_dir, needed_bytes)
            free = disk_free(game_dir)
            if free < needed_bytes * 2:
                warnings.append(
                    "espaco livre fica abaixo de 2x o necessario; o backup ocupa espaco extra"
                )
        except SafetyError as exc:
            errors.append(str(exc))
    if not game_dir.is_dir():
        errors.append(f"diretorio do jogo nao existe: {game_dir}")
        warnings = []
    return Preflight(not errors, errors, warnings)
