"""Catalogo de traducoes: carga, validacao default-deny e indice assinado."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from pathlib import Path

from . import CATALOG_SCHEMA_VERSION

ENGINES = {"godot", "renpy", "unreal", "unity", "rpgmaker", "gamemaker", "unknown"}
PATCH_KINDS = {"godot_translation", "godot_pack_replace"}
INSTALL_METHODS = {"godot_pck_translations", "godot_pck_replace"}
ARTIFACT_TYPES = {"godot_translation", "po", "pck"}
PERMISSION_STATUS = {"granted", "implied", "unknown", "denied"}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
LOCALE_RE = re.compile(r"^[a-z]{2,3}(_[A-Z]{2})?$")
ANTICHEATS = {"eac", "battleye", "vac", "denuvo", "other"}
FORBIDDEN_KEYS = {"script", "command", "cmd", "exec", "postinstall", "preinstall"}


class CatalogError(Exception):
    pass


@dataclasses.dataclass
class Artifact:
    type: str
    url: str
    sha256: str
    size: int


@dataclasses.dataclass
class Translation:
    id: str
    appid: int
    locale: str
    version: str
    patch_kind: str
    artifacts: list[Artifact]
    source: dict
    permission: dict
    install: dict
    uninstall: dict
    files_touched: list[str]
    requires_offline: bool
    title: str = ""

    @property
    def installable(self) -> bool:
        return self.permission.get("status") == "granted"

    @property
    def blocked_reason(self) -> str:
        status = self.permission.get("status")
        if status == "granted":
            return ""
        return f"permissao do tradutor: {status}"


@dataclasses.dataclass
class Game:
    appid: int
    name: str
    engine: dict
    packs: list[str]
    buildids: dict
    risk: dict
    notes: str
    translations: list[Translation]


def _need(cond: bool, msg: str, errors: list[str]) -> None:
    if not cond:
        errors.append(msg)


def _validate_artifact(raw: dict, where: str, errors: list[str]) -> Artifact:
    if not isinstance(raw, dict):
        errors.append(f"{where}: artefato precisa ser objeto")
        return Artifact("", "", "", 0)
    _need(raw.get("type") in ARTIFACT_TYPES, f"{where}: type invalido", errors)
    url = str(raw.get("url", ""))
    _need(url.startswith("https://"), f"{where}: url precisa ser https", errors)
    digest = str(raw.get("sha256", ""))
    _need(bool(SHA256_RE.match(digest)), f"{where}: sha256 invalido", errors)
    size = raw.get("size")
    _need(isinstance(size, int) and size > 0, f"{where}: size invalido", errors)
    return Artifact(str(raw.get("type", "")), url, digest, int(size or 0))


def _validate_translation(raw: dict, appid: int, where: str, errors: list[str]) -> Translation | None:
    if not isinstance(raw, dict):
        errors.append(f"{where}: traducao precisa ser objeto")
        return None
    tid = str(raw.get("id", ""))
    _need(bool(ID_RE.match(tid)), f"{where}: id invalido", errors)
    _need(raw.get("appid") == appid, f"{where}: appid nao combina com o jogo", errors)
    _need(bool(LOCALE_RE.match(str(raw.get("locale", "")))), f"{where}: locale invalido", errors)
    _need(bool(raw.get("version")), f"{where}: version obrigatoria", errors)

    patch = raw.get("patch") or {}
    _need(patch.get("kind") in PATCH_KINDS, f"{where}: patch.kind invalido", errors)
    artifacts_raw = patch.get("artifacts") or []
    _need(isinstance(artifacts_raw, list) and bool(artifacts_raw),
          f"{where}: patch.artifacts vazio", errors)
    artifacts = [_validate_artifact(a, f"{where}.artifact[{i}]", errors)
                 for i, a in enumerate(artifacts_raw if isinstance(artifacts_raw, list) else [])]

    source = raw.get("source") or {}
    _need(source.get("type") in {"curated", "manual"}, f"{where}: source.type invalido", errors)
    _need(bool(source.get("author")), f"{where}: source.author obrigatorio", errors)

    permission = raw.get("permission") or {}
    status = permission.get("status")
    _need(status in PERMISSION_STATUS, f"{where}: permission.status invalido", errors)
    if status == "granted":
        evidence = str(permission.get("evidence_url", ""))
        _need(evidence.startswith("https://"),
              f"{where}: permission.granted exige evidence_url https", errors)
        _need(bool(permission.get("checked_at")), f"{where}: permission.checked_at obrigatorio", errors)

    install = raw.get("install") or {}
    _need(install.get("method") in INSTALL_METHODS, f"{where}: install.method invalido", errors)
    params = install.get("params") or {}
    _need(isinstance(params, dict), f"{where}: install.params precisa ser objeto", errors)
    if isinstance(params, dict):
        bad = FORBIDDEN_KEYS & {str(k).lower() for k in params}
        _need(not bad, f"{where}: params contem chave proibida {sorted(bad)}", errors)

    uninstall = raw.get("uninstall") or {}
    _need(uninstall.get("method") == "manifest_revert", f"{where}: uninstall.method invalido", errors)

    files = raw.get("files_touched")
    _need(isinstance(files, list) and all(isinstance(f, str) for f in files or []),
          f"{where}: files_touched precisa ser lista de strings", errors)
    risk = raw.get("risk") or {}
    _need(isinstance(risk.get("requires_offline"), bool),
          f"{where}: risk.requires_offline obrigatorio", errors)

    return Translation(
        id=tid, appid=appid, locale=str(raw.get("locale", "")),
        version=str(raw.get("version", "")), patch_kind=str(patch.get("kind", "")),
        artifacts=artifacts, source=source, permission=permission, install=install,
        uninstall=uninstall, files_touched=list(files or []),
        requires_offline=bool(risk.get("requires_offline", True)),
        title=str(raw.get("title", "")),
    )


def validate_game(raw: dict, where: str = "game") -> Game:
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise CatalogError(f"{where}: precisa ser objeto")
    appid = raw.get("appid")
    _need(isinstance(appid, int) and appid > 0, f"{where}: appid invalido", errors)
    name = str(raw.get("name", ""))
    _need(bool(name.strip()), f"{where}: name obrigatorio", errors)
    engine = raw.get("engine") or {}
    _need(engine.get("kind") in ENGINES, f"{where}: engine.kind invalido", errors)
    packs = raw.get("packs") or []
    _need(isinstance(packs, list) and all(isinstance(p, str) for p in packs or []),
          f"{where}: packs precisa ser lista de strings", errors)
    buildids = raw.get("buildids") or {}
    _need(isinstance(buildids, (dict, list)), f"{where}: buildids precisa ser objeto", errors)
    if isinstance(buildids, dict):
        _need(all(isinstance(b, str) for b in buildids.get("tested", [])),
              f"{where}: buildids.tested precisa ser lista de strings", errors)
    risk = raw.get("risk") or {}
    anticheat = risk.get("anticheat", [])
    _need(isinstance(anticheat, list) and set(anticheat) <= ANTICHEATS,
          f"{where}: risk.anticheat invalido", errors)
    _need(isinstance(risk.get("online"), bool), f"{where}: risk.online obrigatorio", errors)

    translations: list[Translation] = []
    ids: set[str] = set()
    for i, item in enumerate(raw.get("translations") or []):
        translation = _validate_translation(item, int(appid or 0), f"{where}.translations[{i}]", errors)
        if translation is None:
            continue
        if translation.id in ids:
            errors.append(f"{where}: id de traducao duplicado {translation.id!r}")
        ids.add(translation.id)
        translations.append(translation)

    if errors:
        raise CatalogError("\n".join(errors))
    return Game(int(appid), name, engine, list(packs), dict(buildids), dict(risk),
                str(raw.get("notes", "")), translations)


def load_catalog(root: str | Path) -> list[Game]:
    root = Path(root)
    games_dir = root / "games" if (root / "games").is_dir() else root
    games: list[Game] = []
    seen: set[int] = set()
    errors: list[str] = []
    for path in sorted(games_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            game = validate_game(raw, where=path.name)
        except (json.JSONDecodeError, CatalogError) as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        if game.appid in seen:
            errors.append(f"{path.name}: appid duplicado {game.appid}")
        seen.add(game.appid)
        games.append(game)
    if errors:
        raise CatalogError("\n".join(errors))
    games.sort(key=lambda g: g.name.casefold())
    return games


def build_index(games: list[Game]) -> dict:
    """Indice deterministico (sem timestamps) para o plugin consumir."""
    payload = []
    for game in games:
        payload.append({
            "appid": game.appid,
            "name": game.name,
            "engine": game.engine,
            "packs": game.packs,
            "buildids": game.buildids,
            "risk": game.risk,
            "translations": [
                {
                    "id": t.id,
                    "appid": t.appid,
                    "title": t.title,
                    "locale": t.locale,
                    "version": t.version,
                    "patch": {"kind": t.patch_kind, "artifacts": [dataclasses.asdict(a) for a in t.artifacts]},
                    "source": t.source,
                    "permission": t.permission,
                    "install": t.install,
                    "uninstall": t.uninstall,
                    "files_touched": t.files_touched,
                    "risk": {"requires_offline": t.requires_offline},
                }
                for t in game.translations
            ],
        })
    return {"schema_version": CATALOG_SCHEMA_VERSION, "games": payload}


def validate_index(raw: dict) -> list[Game]:
    """Valida um index.json ja baixado e devolve os jogos."""
    if not isinstance(raw, dict):
        raise CatalogError("indice: precisa ser objeto")
    if raw.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise CatalogError(
            f"indice: schema_version {raw.get('schema_version')!r} nao suportado "
            f"(esperado {CATALOG_SCHEMA_VERSION})"
        )
    items = raw.get("games")
    if not isinstance(items, list):
        raise CatalogError("indice: games precisa ser lista")
    games: list[Game] = []
    seen: set[int] = set()
    for i, item in enumerate(items):
        game = validate_game(item, where=f"index.games[{i}]")
        if game.appid in seen:
            raise CatalogError(f"indice: appid duplicado {game.appid}")
        seen.add(game.appid)
        games.append(game)
    return games


def write_index(root: str | Path, out_dir: str | Path | None = None) -> tuple[Path, Path]:
    root = Path(root)
    games = load_catalog(root)
    data = json.dumps(build_index(games), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    out_dir = Path(out_dir) if out_dir else root
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "index.json"
    index_path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    (out_dir / "index.sha256").write_text(digest + "\n", encoding="utf-8")
    return index_path, out_dir / "index.sha256"


def find_translation(games: list[Game], appid: int, translation_id: str) -> tuple[Game, Translation]:
    for game in games:
        if game.appid != appid:
            continue
        for translation in game.translations:
            if translation.id == translation_id:
                return game, translation
    raise CatalogError(f"traducao {translation_id!r} nao encontrada para o appid {appid}")
