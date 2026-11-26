"""Download com verificacao de SHA-256 e cache local."""

from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from pathlib import Path

from .manifest import state_dir, write_atomic

USER_AGENT = "translate-deck/0.1 (+https://github.com/VictorCabral99/translate-deck)"
MAX_BYTES = 2 * 1024 * 1024 * 1024


class DownloadError(Exception):
    pass


def cache_dir() -> Path:
    return state_dir() / "cache"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_bytes(url: str, timeout: int = 60) -> bytes:
    if not url.startswith("https://"):
        raise DownloadError(f"url precisa ser https: {url!r}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_BYTES:
                raise DownloadError(f"arquivo grande demais: {length} bytes")
            data = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, OSError) as exc:
        raise DownloadError(f"falha ao baixar {url}: {exc}") from exc
    if len(data) > MAX_BYTES:
        raise DownloadError(f"arquivo grande demais: {url}")
    return data


def fetch(url: str, expected_sha256: str, timeout: int = 60) -> Path:
    """Baixa para o cache e devolve o caminho; o hash e sempre verificado."""
    cache = cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    name = f"{_sha256(url.encode('utf-8'))[:16]}-{os.path.basename(url.split('?')[0]) or 'artifact'}"
    target = cache / name
    if target.is_file() and _sha256(target.read_bytes()) == expected_sha256:
        return target
    data = fetch_bytes(url, timeout=timeout)
    actual = _sha256(data)
    if actual != expected_sha256:
        raise DownloadError(f"sha256 nao confere para {url}: esperado {expected_sha256}, obtido {actual}")
    write_atomic(target, data)
    return target


def fetch_text(url: str, expected_sha256: str | None = None, timeout: int = 30) -> str:
    data = fetch_bytes(url, timeout=timeout)
    if expected_sha256 is not None:
        actual = _sha256(data)
        if actual != expected_sha256:
            raise DownloadError(f"sha256 do indice nao confere: esperado {expected_sha256}, obtido {actual}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DownloadError("resposta nao e UTF-8") from exc
