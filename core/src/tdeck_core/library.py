"""Biblioteca local de traducoes fornecidas pelo usuario (build sideload).

Copia o artefato para uma pasta gerenciada, gera um descritor proprio e expoe
as traducoes como `local/<id>` para o patcher. Nada aqui baixa codigo nem
executa nada: apenas arquivos de dados (.translation/.po/.pck/.json) validados.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

from . import manifest as mf
from .catalog import Artifact, Game, Translation
from .detect import detect
from .engines.godot import GodotError, GodotPatcher
from .pck import PckError, read_pack
from .steam import GameInstall, find_install

LIBRARY_PREFIX = "local/"
SCHEMA_VERSION = 1
MAX_ZIP_ENTRIES = 2000
MAX_ZIP_BYTES = 500 * 1024 * 1024
TRANSLATION_SUFFIXES = {".translation": "godot_translation", ".po": "po"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
LOCALE_RE = re.compile(r"^[a-z]{2,3}(_[A-Z]{2})?$")
LOCALE_HINT = re.compile(r"(?<![a-z])(pt[_-]?br|en|es|fr|de|it|ru|ja|ko|zh[_-]?cn)(?![a-z])",
                         re.IGNORECASE)
MODES = {"insert", "replace_pack"}


class LibraryError(Exception):
    pass


@dataclasses.dataclass
class Analysis:
    mode: str                       # insert | replace_pack | descriptor
    artifact: Path | None
    descriptor: Path | None
    sha256: str
    size: int
    display_name: str
    cleanup: Path | None = None


@dataclasses.dataclass
class Entry:
    appid: int
    name: str
    buildid: str
    slug: str
    title: str
    locale: str
    version: str
    kind: str
    artifacts: list[dict]
    targets: list[str]
    origin: str
    added_at: str
    path: Path

    @property
    def ref(self) -> str:
        return f"{LIBRARY_PREFIX}{self.slug}"

    def to_dict(self) -> dict:
        return {
            "appid": self.appid, "name": self.name, "buildid": self.buildid,
            "id": self.slug, "ref": self.ref, "title": self.title,
            "locale": self.locale, "version": self.version, "kind": self.kind,
            "artifacts": self.artifacts, "targets": self.targets,
            "origin": self.origin, "added_at": self.added_at,
        }


def library_root() -> Path:
    return mf.state_dir() / "library"


def is_library_ref(translation_id: str) -> bool:
    return translation_id.startswith(LIBRARY_PREFIX)


def slug_from_ref(translation_id: str) -> str:
    return translation_id.removeprefix(LIBRARY_PREFIX)


def _slug(locale: str, digest: str) -> str:
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", locale.casefold().replace("_", "-")).strip("-.")
    return f"{cleaned or 'und'}-{digest[:8]}"


def _guess_locale(name: str) -> str:
    match = LOCALE_HINT.search(name)
    if not match:
        return "und"
    value = match.group(1).replace("-", "_")
    return value[:2].lower() + value[2:]


def _ensure(cond: bool, message: str) -> None:
    if not cond:
        raise LibraryError(message)


def _safe_zip(path: Path, dest: Path) -> None:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise LibraryError(f"zip invalido: {exc}") from exc
    with archive:
        infos = archive.infolist()
        _ensure(len(infos) <= MAX_ZIP_ENTRIES,
                f"zip com entradas demais ({len(infos)} > {MAX_ZIP_ENTRIES})")
        total = 0
        for info in infos:
            name = info.filename.replace("\\", "/")
            pure = PurePosixPath(name)
            _ensure(not pure.is_absolute(), f"caminho absoluto no zip: {name}")
            _ensure(".." not in pure.parts, f"caminho com '..' no zip: {name}")
            _ensure(not re.match(r"^[a-zA-Z]:", pure.parts[0] if pure.parts else ""),
                    f"caminho com drive no zip: {name}")
            mode = (info.external_attr >> 16) & 0o170000
            _ensure(mode != 0o120000, f"symlink no zip: {name}")
            total += info.file_size
            _ensure(total <= MAX_ZIP_BYTES,
                    f"zip grande demais (>{MAX_ZIP_BYTES // (1024 * 1024)} MB descompactado)")
        dest.mkdir(parents=True, exist_ok=True)
        archive.extractall(dest)


def _pick(root: Path) -> tuple[str, Path | None, Path | None]:
    files = [p for p in root.rglob("*") if p.is_file()]
    jsons = [p for p in files if p.suffix.casefold() == ".json"]
    pcks = [p for p in files if p.suffix.casefold() == ".pck"]
    translations = [p for p in files if p.suffix.casefold() in TRANSLATION_SUFFIXES]
    if len(jsons) == 1:
        return "descriptor", None, jsons[0]
    if len(jsons) > 1:
        names = ", ".join(p.name for p in jsons)
        raise LibraryError(f"mais de um .json na pasta/zip ({names}); informe o arquivo")
    if translations:
        if len(translations) > 1:
            names = ", ".join(p.name for p in translations)
            raise LibraryError(
                f"mais de um arquivo de traducao ({names}); informe qual aplicar"
            )
        return "insert", translations[0], None
    if len(pcks) == 1:
        return "replace_pack", pcks[0], None
    if len(pcks) > 1:
        names = ", ".join(p.name for p in pcks)
        raise LibraryError(f"mais de um .pck ({names}); informe qual e a traducao")
    raise LibraryError("nenhum .translation/.po/.pck/.json encontrado")


def analyze(path_or_url: str | Path) -> Analysis:
    """Inspeciona sem gravar. Chame `cleanup()` no result para zips."""
    raw = Path(os.path.expanduser(str(path_or_url)))
    _ensure(str(path_or_url).strip() != "", "informe um arquivo ou pasta")
    cleanup: Path | None = None
    try:
        if raw.is_dir():
            root, single = raw, None
        elif raw.is_file() and raw.suffix.casefold() == ".zip":
            cleanup = Path(tempfile.mkdtemp(prefix="tdeck-zip-"))
            _safe_zip(raw, cleanup)
            root, single = cleanup, None
        elif raw.is_file():
            root, single = raw.parent, raw
        else:
            raise LibraryError(f"caminho nao existe: {raw}")
        if single is not None:
            suffix = single.suffix.casefold()
            if suffix == ".json":
                mode, artifact, descriptor = "descriptor", None, single
            elif suffix in TRANSLATION_SUFFIXES:
                mode, artifact, descriptor = "insert", single, None
            elif suffix == ".pck":
                mode, artifact, descriptor = "replace_pack", single, None
            else:
                raise LibraryError(
                    f"formato nao suportado: {single.name} (use .translation/.po/.pck/.json/.zip)"
                )
        else:
            mode, artifact, descriptor = _pick(root)
        target = descriptor or artifact
        assert target is not None
        digest = mf.sha256_file(target)
        size = target.stat().st_size
        return Analysis(mode, artifact, descriptor, digest, size, target.name, cleanup)
    except Exception:
        if cleanup is not None:
            shutil.rmtree(cleanup, ignore_errors=True)
        raise


def _translation_entries(pack: Path) -> list[str]:
    try:
        info = read_pack(pack)
    except PckError as exc:
        raise LibraryError(f"pack do jogo ilegivel: {exc}") from exc
    return [entry.norm_path for entry in info.translation_entries]


def _propose_target(pack: Path, artifact_name: str, target: str) -> tuple[str, list[str]]:
    entries = _translation_entries(pack)
    candidates = [f"res://{path}" for path in entries]
    if target:
        target = target if target.startswith("res://") else f"res://{target.lstrip('/')}"
        return target, candidates
    base = Path(artifact_name).name.casefold()
    matches = [path for path in entries if Path(path).name.casefold() == base]
    if len(matches) == 1:
        return f"res://{matches[0]}", candidates
    if len(entries) == 1:
        return f"res://{entries[0]}", candidates
    if not entries:
        raise LibraryError(
            "o pack do jogo nao tem entradas .translation/.po; informe --target "
            "(ou use o .pck traduzido inteiro)"
        )
    return "", candidates


def _install_for(appid: int, install: GameInstall | None) -> GameInstall:
    if install is not None:
        return install
    found = find_install(appid)
    if found is None:
        raise LibraryError(f"appid {appid} nao esta instalado")
    return found


def inspect(appid: int, path_or_url: str | Path, target: str = "",
            install: GameInstall | None = None) -> dict:
    """Analisa o arquivo e o jogo, sem copiar nada. Devolve o plano resumido."""
    install = _install_for(appid, install)
    detection = detect(install.path)
    _ensure(detection.engine == "godot",
            f"engine detectada {detection.engine!r}; a biblioteca local so aplica Godot")
    if detection.anticheat:
        raise LibraryError("anti-cheat detectado: " + ", ".join(detection.anticheat))
    try:
        pack = GodotPatcher.resolve_pack(install.path, {})
    except GodotError as exc:
        raise LibraryError(str(exc)) from exc
    pack_info = read_pack(pack)

    analysis = analyze(path_or_url)
    try:
        warnings: list[str] = []
        if analysis.mode == "descriptor":
            destination, candidates = "", []
            required = pack.stat().st_size * 2 + analysis.size
            warnings.append("descritor .json aplica os artefatos por URL (hash conferido no download)")
        elif analysis.mode == "replace_pack":
            try:
                read_pack(analysis.artifact)  # type: ignore[arg-type]
            except PckError as exc:
                raise LibraryError(f"o .pck informado nao e um pack Godot valido: {exc}") from exc
            destination, candidates = "", []
            required = pack.stat().st_size + analysis.size
            warnings.append("substitui o pack inteiro; o backup permite reverter")
        else:
            destination, candidates = _propose_target(pack, analysis.display_name, target)
            if not destination:
                warnings.append("mais de uma entrada de traducao no pack; escolha o destino")
            elif destination not in candidates:
                warnings.append(
                    f"{destination} nao existe no pack; sera adicionado (o jogo pode ignora-lo)"
                )
            required = pack.stat().st_size * 2 + analysis.size
        free = shutil.disk_usage(str(install.path)).free
        if free < required:
            raise LibraryError(
                f"espaco insuficiente: precisa {required // (1024 * 1024)} MB, "
                f"livre {free // (1024 * 1024)} MB"
            )
        return {
            "ok": True,
            "appid": install.appid,
            "game": install.name,
            "game_dir": str(install.path),
            "pack": pack.name,
            "pack_layout": pack_info.layout,
            "engine": "godot",
            "mode": analysis.mode,
            "artifact": analysis.display_name,
            "sha256": analysis.sha256,
            "size": analysis.size,
            "locale": _guess_locale(analysis.display_name),
            "target": destination,
            "candidates": candidates,
            "required_bytes": required,
            "warnings": warnings,
        }
    finally:
        if analysis.cleanup is not None:
            shutil.rmtree(analysis.cleanup, ignore_errors=True)


def add(appid: int, path_or_url: str | Path, target: str = "",
        install: GameInstall | None = None) -> Entry:
    """Copia o artefato para a biblioteca e registra a traducao como local/<id>."""
    install = _install_for(appid, install)
    report = inspect(appid, path_or_url, target, install)
    if report["mode"] == "insert" and not report["target"]:
        raise LibraryError(
            "mais de uma entrada de traducao no pack; escolha o destino entre: "
            + ", ".join(report["candidates"])
        )
    analysis = analyze(path_or_url)
    try:
        slug = _slug(report["locale"], analysis.sha256)
        entry_dir = library_root() / str(appid) / slug
        meta_path = entry_dir / "descriptor.json"
        if meta_path.is_file():
            existing = _load_entry(meta_path)
            if existing.artifacts and existing.artifacts[0]["sha256"] == analysis.sha256:
                return existing
            raise LibraryError(f"ja existe entrada {slug!r} com conteudo diferente")

        files_dir = entry_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[dict] = []
        if analysis.mode == "descriptor":
            assert analysis.descriptor is not None
            destination = files_dir / "translation.json"
            shutil.copyfile(analysis.descriptor, destination)
            kind = "descriptor"
            targets: list[str] = []
        else:
            assert analysis.artifact is not None
            mode = "replace_pack" if analysis.mode == "replace_pack" else "insert"
            name = Path(analysis.display_name).name
            destination = files_dir / name
            shutil.copyfile(analysis.artifact, destination)
            kind = mode
            artifact_type = ("pck" if mode == "replace_pack"
                             else TRANSLATION_SUFFIXES[Path(name).suffix.casefold()])
            artifacts.append({
                "name": name, "type": artifact_type,
                "sha256": mf.sha256_file(destination),
                "size": destination.stat().st_size,
            })
            targets = [report["target"]] if mode == "insert" else []

        locale = report.get("locale") or _guess_locale(report["artifact"])
        title = Path(report["artifact"]).stem or "traducao local"
        meta = {
            "schema_version": SCHEMA_VERSION,
            "appid": appid,
            "name": install.name,
            "buildid": install.buildid,
            "engine": {"kind": "godot"},
            "translation": {
                "id": slug, "title": title, "locale": locale, "version": "local",
                "kind": kind, "artifacts": artifacts, "targets": targets,
                "origin": str(Path(os.path.expanduser(str(path_or_url)))),
                "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }
        mf.write_atomic(meta_path, json.dumps(meta, indent=2, ensure_ascii=False).encode("utf-8"))
        return _load_entry(meta_path)
    finally:
        if analysis.cleanup is not None:
            shutil.rmtree(analysis.cleanup, ignore_errors=True)


def _load_entry(meta_path: Path) -> Entry:
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LibraryError(f"entrada ilegivel: {meta_path} ({exc})") from exc
    _ensure(raw.get("schema_version") == SCHEMA_VERSION,
            f"entrada com schema desconhecido: {meta_path}")
    translation = raw.get("translation") or {}
    slug = str(translation.get("id", ""))
    _ensure(bool(SLUG_RE.match(slug)), f"id invalido na entrada {meta_path}")
    _ensure(translation.get("kind") in MODES | {"descriptor"},
            f"kind invalido na entrada {meta_path}")
    artifacts = translation.get("artifacts") or []
    for item in artifacts:
        _ensure(bool(SHA256_RE.match(str(item.get("sha256", "")))),
                f"sha256 invalido na entrada {meta_path}")
    targets = list(translation.get("targets") or [])
    return Entry(
        appid=int(raw.get("appid", 0)), name=str(raw.get("name", "")),
        buildid=str(raw.get("buildid", "")), slug=slug,
        title=str(translation.get("title", "")), locale=str(translation.get("locale", "und")),
        version=str(translation.get("version", "local")), kind=str(translation.get("kind", "")),
        artifacts=artifacts, targets=targets,
        origin=str(translation.get("origin", "")), added_at=str(translation.get("added_at", "")),
        path=meta_path.parent,
    )


def list_entries(appid: int | None = None) -> list[Entry]:
    root = library_root()
    entries: list[Entry] = []
    if not root.is_dir():
        return entries
    pattern = f"{appid}/" if appid is not None else "*/"
    for meta_path in sorted(root.glob(f"{pattern}*/descriptor.json")):
        try:
            entries.append(_load_entry(meta_path))
        except LibraryError:
            continue
    return sorted(entries, key=lambda e: (e.name.casefold(), e.title.casefold(), e.slug))


def get(appid: int, translation_id: str) -> Entry:
    slug = slug_from_ref(translation_id)
    _ensure(bool(SLUG_RE.match(slug)), f"id de biblioteca invalido: {translation_id!r}")
    meta_path = library_root() / str(appid) / slug / "descriptor.json"
    _ensure(meta_path.is_file(), f"traducao local {translation_id!r} nao encontrada")
    return _load_entry(meta_path)


def remove(appid: int, translation_id: str) -> Entry:
    entry = get(appid, translation_id)
    current = mf.load(appid)
    if current is not None and current.translation_id == entry.ref:
        raise LibraryError("reverta a traducao antes de remover da biblioteca")
    shutil.rmtree(entry.path, ignore_errors=True)
    return entry


def build(appid: int, translation_id: str) -> tuple[Game, Translation, list[Path] | None]:
    """Monta Game/Translation para o patcher. `None` = artefatos remotos (descritor)."""
    entry = get(appid, translation_id)
    files_dir = entry.path / "files"
    if entry.kind == "descriptor":
        from .sources.manual import load as load_manual
        descriptor = files_dir / "translation.json"
        _ensure(descriptor.is_file(), f"descritor ausente: {descriptor}")
        game, translation, _ = load_manual(str(descriptor), appid)
        return game, translation, None

    paths = [files_dir / item["name"] for item in entry.artifacts]
    for item, path in zip(entry.artifacts, paths):
        _ensure(path.is_file(), f"artefato ausente na biblioteca: {path}")
        _ensure(mf.sha256_file(path) == item["sha256"],
                f"artefato alterado na biblioteca: {path}")

    artifacts = [
        Artifact(type=item["type"], url=f"local://{item['name']}",
                 sha256=item["sha256"], size=int(item["size"]))
        for item in entry.artifacts
    ]
    if entry.kind == "replace_pack":
        patch_kind, method = "godot_pack_replace", "godot_pck_replace"
        params = {"replace_pack": True}
        files_touched: list[str] = []
    else:
        patch_kind, method = "godot_translation", "godot_pck_translations"
        params = {"insert": [{"pck_path": target, "artifact": index}
                             for index, target in enumerate(entry.targets)]}
        files_touched = []
    translation = Translation(
        id=entry.ref, appid=appid, locale=entry.locale, version=entry.version,
        patch_kind=patch_kind, artifacts=artifacts,
        source={"type": "manual", "author": "usuario", "origin_url": "local"},
        permission={"status": "unknown"},
        install={"method": method, "params": params},
        uninstall={"method": "manifest_revert"}, files_touched=files_touched,
        requires_offline=True, title=entry.title,
    )
    game = Game(appid=appid, name=entry.name or f"App {appid}",
                engine={"kind": "godot"}, packs=[], buildids={}, risk={},
                notes="entrada da biblioteca local", translations=[translation])
    return game, translation, paths


def load_target(install: GameInstall, appid: int, translation_id: str):
    from .engines import PATCHERS
    game, translation, artifact_paths = build(appid, translation_id)
    patcher = PATCHERS.get("godot")
    if patcher is None:
        raise LibraryError("patcher godot indisponivel")
    return install, game, translation, patcher, artifact_paths
