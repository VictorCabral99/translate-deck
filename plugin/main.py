import asyncio
import importlib
import json
import logging
import os
import sys
import threading
import uuid
from pathlib import Path

import decky

sys.path.append(os.path.join(decky.DECKY_PLUGIN_DIR, "py_modules"))
sys.path.append(decky.DECKY_PLUGIN_DIR)

from tdeck_core import catalog as cat, download, manifest as mf, safety  # noqa: E402
from tdeck_core.engines import PATCHERS  # noqa: E402,F401  (registra patchers)
from tdeck_core.steam import SteamError, find_install, find_installs  # noqa: E402

INDEX_URL = "https://victorcabral99.github.io/translate-deck-catalog/index.json"
INDEX_SHA256 = ""  # preencher com o sha256 do indice publicado; vazio = recusa
CACHE_INDEX = "catalog-index.json"

_jobs: dict[str, dict] = {}
_log_path = Path(decky.DECKY_PLUGIN_LOG_DIR) / "translate-deck.log"


def _log(message: str) -> None:
    decky.logger.info(message)
    try:
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        with _log_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


def _runtime() -> Path:
    path = Path(decky.DECKY_PLUGIN_RUNTIME_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_games() -> list:
    cached = _runtime() / CACHE_INDEX
    if cached.is_file():
        games = cat.validate_index(json.loads(cached.read_text(encoding="utf-8")))
        return games
    raise cat.CatalogError("catalogo ainda nao baixado; use Atualizar catalogo")


def _manual_module():
    try:
        return importlib.import_module("manual_wiring")
    except ImportError:
        return None


def _job(job_id: str, message: str, done: bool = False, error: str = "") -> None:
    _jobs[job_id] = {"id": job_id, "message": message, "done": done, "error": error}
    _log(f"[{job_id}] {message}")


def _run(appid: int, dry_run: bool, action) -> str:
    job_id = uuid.uuid4().hex[:8]

    def worker() -> None:
        try:
            _job(job_id, "iniciando")
            action(job_id)
        except Exception as exc:  # noqa: BLE001
            _log(f"[{job_id}] erro: {exc}")
            _job(job_id, "falhou", done=True, error=str(exc))

    _jobs[job_id] = {"id": job_id, "message": "na fila", "done": False, "error": ""}
    threading.Thread(target=worker, daemon=True, name=f"tdeck-{appid}-{job_id}").start()
    return job_id


class Plugin:
    async def _main(self):
        _log("translate-deck iniciado")

    async def _unload(self):
        _log("translate-deck descarregado")

    async def refresh_catalog(self):
        if not INDEX_SHA256:
            return {"ok": False, "error": "indice sem sha256 fixado nesta build"}
        text = await asyncio.to_thread(download.fetch_text, INDEX_URL, INDEX_SHA256)
        raw = json.loads(text)
        games = cat.validate_index(raw)
        (_runtime() / CACHE_INDEX).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        _log(f"catalogo atualizado: {len(games)} jogos")
        return {"ok": True, "games": len(games)}

    async def list_games(self):
        try:
            catalog = {game.appid: game for game in _load_games()}
        except cat.CatalogError as exc:
            return {"ok": False, "error": str(exc), "games": []}
        installs = await asyncio.to_thread(find_installs)
        rows = []
        for install in installs:
            game = catalog.get(install.appid)
            current = mf.load(install.appid)
            rows.append({
                "appid": install.appid,
                "name": install.name,
                "buildid": install.buildid,
                "installed_translation": current.translation_id if current else "",
                "translations": [
                    {"id": t.id, "title": t.title or t.id, "locale": t.locale,
                     "version": t.version, "installable": t.installable,
                     "blocked": t.blocked_reason, "source": t.source.get("author", ""),
                     "permission": t.permission.get("status", "")}
                    for t in (game.translations if game else [])
                ],
            })
        return {"ok": True, "games": rows}

    async def plan(self, appid: int, translation_id: str, manual_path: str = ""):
        try:
            install, game, translation, patcher = await asyncio.to_thread(
                self._target, appid, translation_id, manual_path)
            plan = await asyncio.to_thread(patcher.plan, install, game, translation, None, False)
            return {"ok": True, "plan": plan.describe()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    async def install(self, appid: int, translation_id: str, dry_run: bool = True,
                      manual_path: str = ""):
        if dry_run:
            return await self.plan(appid, translation_id, manual_path)
        try:
            install, game, translation, patcher = await asyncio.to_thread(
                self._target, appid, translation_id, manual_path)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

        def action(job_id: str) -> None:
            paths = []
            for artifact in translation.artifacts:
                _job(job_id, f"baixando {artifact.url.rsplit('/', 1)[-1]}")
                paths.append(download.fetch(artifact.url, artifact.sha256))
            _job(job_id, "aplicando patch")
            plan = patcher.plan(install, game, translation, paths, True)
            result = patcher.apply(plan)
            _job(job_id, result.message, done=True, error="" if result.ok else result.message)

        return {"ok": True, "job": _run(appid, dry_run, action)}

    async def uninstall(self, appid: int):
        try:
            install = await asyncio.to_thread(find_install, appid)
            if install is None:
                return {"ok": False, "error": "jogo nao instalado"}
            patcher = self._patcher_for(appid, install.path)
            result = await asyncio.to_thread(patcher.uninstall, appid, install.path)
            return {"ok": result.ok, "message": result.message}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    async def verify(self, appid: int):
        try:
            install = await asyncio.to_thread(find_install, appid)
            if install is None:
                return {"ok": False, "error": "jogo nao instalado"}
            patcher = self._patcher_for(appid, install.path)
            result = await asyncio.to_thread(patcher.verify, appid, install.path)
            return {"ok": result.ok, "status": result.status, "message": result.message,
                    "files": result.files}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    async def get_job(self, job_id: str):
        return _jobs.get(job_id, {"id": job_id, "message": "desconhecido", "done": True})

    async def read_log(self, lines: int = 200):
        try:
            content = _log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {"ok": True, "lines": []}
        return {"ok": True, "lines": content[-int(lines):]}

    async def manual_source_available(self):
        return {"ok": True, "available": _manual_module() is not None}

    def _target(self, appid: int, translation_id: str, manual_path: str):
        install = find_install(appid)
        if install is None:
            raise SteamError(f"appid {appid} nao esta instalado")
        if manual_path:
            module = _manual_module()
            if module is None:
                raise RuntimeError("fonte manual indisponivel nesta edicao (loja)")
            return module.load_target(install, appid, translation_id, manual_path)
        game, translation = cat.find_translation(_load_games(), appid, translation_id)
        if not translation.installable:
            raise RuntimeError(f"traducao bloqueada: {translation.blocked_reason}")
        patcher = PATCHERS.get(game.engine.get("kind", ""))
        if patcher is None:
            raise RuntimeError(f"engine {game.engine.get('kind')!r} nao suportada")
        return install, game, translation, patcher

    @staticmethod
    def _patcher_for(appid: int, game_dir: Path):
        from tdeck_core.detect import detect
        engine = detect(game_dir).engine
        patcher = PATCHERS.get(engine)
        if patcher is None:
            raise RuntimeError(f"engine {engine!r} nao suportada")
        return patcher
