"""Leitor e escritor minimo do formato PCK do Godot (magic GDPC).

Layouts suportados (fonte: godot/core/io/file_access_pack.cpp):

  V1 (Godot 3.x): magic, version, engine(3xu32), 16xu32 reservado, count,
      tabela logo apos o cabecalho, offsets absolutos.
  V2 (Godot 4.0-4.3): + pack_flags(u32), file_base(u64), 16xu32 reservado,
      count, tabela apos o cabecalho; offsets relativos a file_base.
  V3/V4 (Godot 4.4+): + dir_offset(u64) logo apos file_base; a tabela fica no
      fim do arquivo (posicao dir_offset) e os offsets sao relativos.

Entrada: u32 len, bytes utf8 (sem padding), u64 offset, u64 size, md5[16] e,
a partir do V2, u32 flags.

Packs com diretorio criptografado, sparse bundle, ou arquivos com flags
(criptografado/removido/delta) sao recusados para escrita.
"""

from __future__ import annotations

import dataclasses
import hashlib
import struct
from contextlib import nullcontext
from pathlib import Path

MAGIC = b"GDPC"
ALIGNMENT = 16
RESERVED_U32 = 16
MAX_FILES = 500_000
MAX_PATH = 8192

PACK_DIR_ENCRYPTED = 1 << 0
PACK_REL_FILEBASE = 1 << 1
PACK_SPARSE_BUNDLE = 1 << 2
PACK_FILE_FLAGS_MASK = 1 << 0 | 1 << 1 | 1 << 2


class PckError(Exception):
    pass


def _md5(data: bytes) -> bytes:
    try:
        return hashlib.md5(data, usedforsecurity=False).digest()
    except TypeError:  # Python < 3.9
        return hashlib.md5(data).digest()


def _align(value: int, alignment: int = ALIGNMENT) -> int:
    return (value + alignment - 1) // alignment * alignment


@dataclasses.dataclass
class PckEntry:
    path: str
    offset: int
    size: int
    md5: bytes
    flags: int = 0

    @property
    def norm_path(self) -> str:
        return self.path[6:] if self.path.startswith("res://") else self.path


@dataclasses.dataclass
class PckInfo:
    layout: str
    format_version: int
    engine: tuple[int, int, int]
    file_base: int
    entries: list[PckEntry]
    header_offset: int = 0
    pack_flags: int = 0

    @property
    def encrypted(self) -> bool:
        return bool(self.pack_flags & PACK_DIR_ENCRYPTED)

    @property
    def engine_str(self) -> str:
        return ".".join(str(x) for x in self.engine)

    def find(self, path: str) -> PckEntry | None:
        want = path[6:] if path.startswith("res://") else path
        for entry in self.entries:
            if entry.norm_path == want:
                return entry
        return None

    @property
    def translation_entries(self) -> list[PckEntry]:
        suffixes = (".translation", ".po")
        return [e for e in self.entries if e.norm_path.lower().endswith(suffixes)]


def _layout_for(version: int) -> str:
    if version == 1:
        return "godot3"
    if version == 2:
        return "godot4"
    return "godot44"


def _version_for(layout: str) -> int:
    return {"godot3": 1, "godot4": 2, "godot44": 4}[layout]


def _read_exact(handle, count: int) -> bytes:
    data = handle.read(count)
    if len(data) != count:
        raise PckError(f"fim de arquivo inesperado (faltaram {count - len(data)} bytes)")
    return data


def _u32(handle) -> int:
    return struct.unpack("<I", _read_exact(handle, 4))[0]


def _u64(handle) -> int:
    return struct.unpack("<Q", _read_exact(handle, 8))[0]


def entry_pos(info: PckInfo, entry: PckEntry) -> int:
    """Posicao absoluta dos bytes da entrada no arquivo."""
    return entry.offset if info.format_version == 1 else info.file_base + entry.offset


def _parse_table(handle, table_pos: int, count: int, version: int) -> list[PckEntry]:
    handle.seek(table_pos)
    entries: list[PckEntry] = []
    for _ in range(count):
        path_len = _u32(handle)
        if not 1 <= path_len <= MAX_PATH:
            raise PckError(f"tamanho de caminho invalido: {path_len}")
        raw = _read_exact(handle, path_len)
        try:
            path = raw.decode("utf-8").rstrip("\x00")
        except UnicodeDecodeError as exc:
            raise PckError("caminho nao-UTF8 na tabela") from exc
        if not path:
            raise PckError("caminho vazio na tabela")
        offset = _u64(handle)
        size = _u64(handle)
        digest = _read_exact(handle, 16)
        flags = _u32(handle) if version >= 2 else 0
        entries.append(PckEntry(path, offset, size, digest, flags))
    return entries


def read_pack(path: str | Path, header_offset: int | None = None) -> PckInfo:
    """Le cabecalho e tabela de um .pck externo ou de um pack embutido no exe."""
    path = Path(path)
    file_size = path.stat().st_size
    with path.open("rb") as handle:
        if header_offset is None:
            handle.seek(0)
            if handle.read(4) != MAGIC:
                raise PckError(f"{path.name} nao e um PCK do Godot (magic ausente)")
            header_offset = 0
        handle.seek(header_offset)
        if _read_exact(handle, 4) != MAGIC:
            raise PckError("magic GDPC ausente no offset informado")
        version = _u32(handle)
        major = _u32(handle)
        minor = _u32(handle)
        patch = _u32(handle)
        if version not in (1, 2, 3, 4):
            raise PckError(f"versao de pack nao suportada: {version}")

        flags = 0
        file_base = 0
        table_pos = 0
        if version == 1:
            handle.seek(header_offset + 20 + RESERVED_U32 * 4)
        elif version == 2:
            flags = _u32(handle)
            file_base = _u64(handle)
            if flags & PACK_DIR_ENCRYPTED:
                raise PckError("diretorio do pack criptografado; nao suportado")
            if flags & PACK_REL_FILEBASE:
                file_base += header_offset
            handle.seek(header_offset + 20 + 4 + 8 + RESERVED_U32 * 4)
        else:
            flags = _u32(handle)
            file_base = _u64(handle) + header_offset
            dir_offset = _u64(handle) + header_offset
            if flags & PACK_DIR_ENCRYPTED:
                raise PckError("diretorio do pack criptografado; nao suportado")
            if flags & PACK_SPARSE_BUNDLE:
                raise PckError("pack sparse bundle; nao suportado")
            if not 0 < dir_offset < file_size:
                raise PckError(f"dir_offset invalido: {dir_offset}")
            handle.seek(dir_offset)

        table_pos = handle.tell()
        count = _u32(handle)
        if not 1 <= count <= MAX_FILES:
            raise PckError(f"contagem de arquivos invalida: {count}")
        entries = _parse_table(handle, handle.tell(), count, version)

    info = PckInfo(_layout_for(version), version, (major, minor, patch), file_base,
                   entries, header_offset, flags)
    _valid_entries(info, file_size)
    return info


def _valid_entries(info: PckInfo, file_size: int) -> None:
    if not info.entries:
        raise PckError("pack sem entradas")
    seen: set[str] = set()
    for entry in info.entries:
        start = entry_pos(info, entry)
        if start < 0 or entry.size < 0 or start + entry.size > file_size:
            raise PckError(f"entrada fora do arquivo: {entry.path!r}")
        if entry.path in seen:
            raise PckError(f"caminho duplicado no pack: {entry.path!r}")
        if any(ord(c) < 32 for c in entry.path):
            raise PckError(f"caminho invalido no pack: {entry.path!r}")
        seen.add(entry.path)


def find_embedded_pack(exe_path: str | Path) -> int | None:
    """Procura o cabecalho de um PCK anexado ao executavel (sem reescrever)."""
    exe_path = Path(exe_path)
    file_size = exe_path.stat().st_size
    with exe_path.open("rb") as handle:
        if file_size >= 12:
            handle.seek(file_size - 12)
            trailer = handle.read(12)
            if trailer[8:] == MAGIC:  # GDPC | u64 tamanho do pack | GDPC
                pack_size = struct.unpack("<Q", trailer[:8])[0]
                header = file_size - pack_size - 12
                if 0 <= header < file_size:
                    try:
                        read_pack(exe_path, header_offset=header)
                        return header
                    except PckError:
                        pass
        window = min(file_size, 4 * 1024 * 1024)
        handle.seek(file_size - window)
        tail = handle.read(window)
    start = 0
    while True:
        idx = tail.find(MAGIC, start)
        if idx < 0:
            return None
        offset = file_size - window + idx
        try:
            read_pack(exe_path, header_offset=offset)
        except PckError:
            start = idx + 1
            continue
        return offset


def extract(archive: str | Path, entry: PckEntry | str, info: PckInfo | None = None,
            header_offset: int | None = None) -> bytes:
    archive = Path(archive)
    if info is None:
        info = read_pack(archive, header_offset)
    if isinstance(entry, str):
        found = info.find(entry)
        if found is None:
            raise PckError(f"entrada {entry!r} nao encontrada")
        entry = found
    with archive.open("rb") as handle:
        handle.seek(entry_pos(info, entry))
        return _read_exact(handle, entry.size)


def entry_offset(info: PckInfo, path: str) -> int:
    entry = info.find(path)
    if entry is None:
        raise PckError(f"entrada {path!r} nao encontrada")
    return entry_pos(info, entry)


def _entry_table_size(path: str, version: int) -> int:
    raw = path.encode("utf-8")
    return 4 + len(raw) + 8 + 8 + 16 + (4 if version >= 2 else 0)


def _write_entries(handle, entries: list[PckEntry], version: int) -> None:
    for entry in entries:
        raw = entry.path.encode("utf-8")
        handle.write(struct.pack("<I", len(raw)))
        handle.write(raw)
        handle.write(struct.pack("<QQ", entry.offset, entry.size))
        handle.write(entry.md5)
        if version >= 2:
            handle.write(struct.pack("<I", entry.flags))


def _write_streaming(destination: Path, version: int, engine: tuple[int, int, int],
                     planned: list[tuple[str, int, bytes | None, bytes, int]],
                     source: Path | None, source_info: PckInfo | None) -> PckInfo:
    """planned: (path, size, payload|None, md5, flags)."""
    table_size = sum(_entry_table_size(p[0], version) for p in planned)
    if version == 1:
        header_size = 20 + RESERVED_U32 * 4 + 4
        file_base = 0
        data_start = _align(header_size + table_size)
    elif version == 2:
        header_size = 20 + 4 + 8 + RESERVED_U32 * 4 + 4
        file_base = _align(header_size + table_size)
        data_start = file_base
    else:
        header_size = 20 + 4 + 8 + 8
        file_base = _align(header_size)
        data_start = file_base

    positioned: list[PckEntry] = []
    src_context = source.open("rb") if source else nullcontext(None)
    with destination.open("wb") as out, src_context as src:
        out.write(b"\x00" * (data_start or 1))
        out.seek(data_start)
        for path, size, payload, md5, flags in planned:
            start = out.tell()
            if payload is not None:
                out.write(payload)
            else:
                src.seek(entry_pos(source_info, source_info.find(path)))
                remaining = size
                while remaining:
                    chunk = src.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise PckError(f"entrada {path!r} truncada")
                    out.write(chunk)
                    remaining -= len(chunk)
            offset = start if version == 1 else start - file_base
            positioned.append(PckEntry(path, offset, size, md5, flags))
            out.write(b"\x00" * (_align(size) - size))

        dir_pos = out.tell()
        if version >= 3:
            file_base = data_start
            out.write(struct.pack("<I", len(positioned)))
            _write_entries(out, positioned, version)

        if version >= 3:
            header = struct.pack("<IIIIIQQ", version, *engine, PACK_REL_FILEBASE,
                                 file_base, dir_pos)
        elif version == 2:
            header = struct.pack("<IIIIIQ", version, *engine, 0, file_base)
            header += b"\x00" * (RESERVED_U32 * 4) + struct.pack("<I", len(positioned))
        else:
            header = struct.pack("<IIII", version, *engine)
            header += b"\x00" * (RESERVED_U32 * 4) + struct.pack("<I", len(positioned))
        out.seek(0)
        out.write(MAGIC + header)

        if version <= 2:
            out.seek(len(MAGIC) + len(header))
            _write_entries(out, positioned, version)

    return PckInfo(_layout_for(version), version, engine, file_base, positioned, 0,
                   PACK_REL_FILEBASE if version >= 3 else 0)


def _check_rewritable(info: PckInfo) -> None:
    if info.header_offset != 0:
        raise PckError("packs embutidos no executavel ainda nao podem ser reescritos")
    if info.encrypted:
        raise PckError("diretorio criptografado; nao suportado")
    for entry in info.entries:
        if entry.flags & PACK_FILE_FLAGS_MASK:
            raise PckError(f"entrada {entry.path!r} com flags {entry.flags:#x}; nao suportado")


def rewrite_pack(
    source: str | Path,
    destination: str | Path,
    replacements: dict[str, bytes] | None = None,
    additions: list[tuple[str, bytes]] | None = None,
    removals: set[str] | None = None,
) -> PckInfo:
    """Reescreve o pack copiando as entradas e trocando/adicionando as pedidas."""
    source = Path(source)
    destination = Path(destination)
    info = read_pack(source)
    _check_rewritable(info)

    replacements = {k[6:] if k.startswith("res://") else k: v for k, v in (replacements or {}).items()}
    removals = {k[6:] if k.startswith("res://") else k for k in (removals or [])}

    planned: list[tuple[str, int, bytes | None, bytes, int]] = []
    for entry in info.entries:
        if entry.norm_path in removals:
            continue
        payload = replacements.get(entry.norm_path)
        planned.append((entry.path, len(payload) if payload is not None else entry.size,
                        payload, _md5(payload) if payload is not None else entry.md5, 0))
    existing = {p[0][6:] if p[0].startswith("res://") else p[0] for p in planned}
    for path, payload in additions or []:
        norm = path[6:] if path.startswith("res://") else path
        if norm in existing:
            raise PckError(f"entrada {path!r} ja existe no pack")
        existing.add(norm)
        planned.append((path, len(payload), payload, _md5(payload), 0))

    return _write_streaming(destination, info.format_version, info.engine, planned,
                            source, info)


def create_pack(destination: str | Path, files: dict[str, bytes], layout: str = "godot3",
                engine: tuple[int, int, int] = (3, 5, 3)) -> PckInfo:
    """Cria um PCK do zero (fixtures e testes)."""
    version = _version_for(layout)
    planned = [(path, len(data), data, _md5(data), 0) for path, data in files.items()]
    return _write_streaming(Path(destination), version, engine, planned, None, None)
