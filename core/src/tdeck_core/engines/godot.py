"""Patcher de traducao para Godot 3.x/4.x.

Grava as entradas de traducao no .pck do jogo com backup byte-exato e
restauracao. Artefatos "godot_translation" prontos nao precisam de ferramenta
externa; artefatos CSV exigem o GDRE Tools configurado no catalogo.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import manifest as mf, safety
from ..catalog import Game, Translation
from ..detect import detect
from ..pck import PckError, find_embedded_pack, read_pack, rewrite_pack
from ..steam import GameInstall
from .base import ApplyResult, InstallPlan, register


class GodotError(Exception):
    pass


@register
class GodotPatcher:
    kind = "godot"

    @staticmethod
    def resolve_pack(game_dir: Path, params: dict) -> Path:
        explicit = params.get("pck")
        if explicit:
            path = Path(explicit)
            if not path.is_absolute():
                path = game_dir / path
            if not path.is_file():
                raise GodotError(f"pack indicado no catalogo nao existe: {path}")
            return path
        candidates = sorted(p for p in game_dir.glob("*.pck") if p.is_file())
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            for exe in game_dir.glob("*.exe"):
                if find_embedded_pack(exe) is not None:
                    raise GodotError(
                        f"{exe.name} tem o pack embutido; escrever em pack embutido ainda nao e suportado"
                    )
            raise GodotError("nenhum .pck externo encontrado")
        names = ", ".join(c.name for c in candidates)
        raise GodotError(f"mais de um .pck ({names}); defina install.params.pck no catalogo")

    @staticmethod
    def _render_override(settings: dict) -> bytes:
        sections: dict[str, list[str]] = {}
        for key, value in settings.items():
            section, _, name = key.partition("/")
            sections.setdefault(section, []).append(f"{name}={_render_value(value)}")
        lines: list[str] = []
        for section, items in sections.items():
            lines.append(f"[{section}]")
            lines.extend(items)
            lines.append("")
        return "\n".join(lines).encode("utf-8")

    @classmethod
    def plan(cls, install: GameInstall, game: Game, translation: Translation,
             artifact_paths: list[Path] | None, apply: bool) -> InstallPlan:
        game_dir = install.path
        if game.engine.get("kind") != cls.kind:
            raise GodotError(f"engine do catalogo nao e godot: {game.engine.get('kind')}")
        if translation.patch_kind == "godot_pack_replace":
            return cls._plan_replace(install, game, translation, artifact_paths, apply)

        detection = detect(game_dir)
        running = safety.processes_running([install.installdir, game_dir.name])
        params = translation.install.get("params") or {}
        pack = cls.resolve_pack(game_dir, params)
        info = read_pack(pack)

        catalog_anticheat = list(game.risk.get("anticheat") or [])
        needed = pack.stat().st_size * 2 + sum(a.size for a in translation.artifacts)
        pre = safety.preflight(game_dir, cls.kind, detection.engine, detection.anticheat,
                               needed, running)
        errors = list(pre.errors)
        if catalog_anticheat:
            errors.append("catalogo marca anti-cheat: " + ", ".join(catalog_anticheat))
        if game.risk.get("online"):
            errors.append("jogo com componente online: aplicar traducao nao e permitido")
        if errors:
            raise GodotError("; ".join(errors))

        insert = params.get("insert") or []
        if not insert:
            raise GodotError("install.params.insert vazio")
        if len(translation.artifacts) > 1 and any("artifact" not in item for item in insert):
            raise GodotError("com varios artefatos, cada insert precisa de 'artifact'")

        tool = "tdeck-pck"
        gdre = None
        if str(params.get("tool", "")).casefold() == "gdre":
            gdre = cls._gdre_binary(params)
            tool = "gdre"

        replacements: dict[str, bytes] = {}
        additions: list[tuple[str, bytes]] = []
        writes: list[tuple[str, int]] = []
        warnings: list[str] = []

        for index, item in enumerate(insert):
            pck_path = str(item.get("pck_path", ""))
            if not pck_path:
                raise GodotError(f"insert[{index}] sem pck_path")
            artifact_index = int(item.get("artifact", 0 if len(translation.artifacts) == 1 else -1))
            if artifact_index < 0 or artifact_index >= len(translation.artifacts):
                raise GodotError(f"insert[{index}] com artifact invalido")
            artifact = translation.artifacts[artifact_index]
            if artifact.type == "godot_translations_csv":
                raise GodotError(
                    "artefato CSV nao suportado: o GDRE v2.7.x nao converte CSV "
                    "(--patch-translations exige projeto/import). Publique .translation/.po."
                )
            if apply:
                if artifact_paths is None:
                    raise GodotError(f"artefato {artifact.url} nao baixado")
                data = artifact_paths[artifact_index].read_bytes()
            else:
                writes.append((pck_path, artifact.size))
                continue
            if info.find(pck_path) is not None:
                replacements[pck_path] = data
            else:
                additions.append((pck_path, data))
            writes.append((pck_path, len(data)))

        if not info.translation_entries:
            warnings.append("o pack nao tem entradas .translation conhecidas; confirme o path")

        created: list[str] = []
        override = params.get("project_settings")
        override_bytes = b""
        if override:
            if not isinstance(override, dict):
                raise GodotError("install.params.project_settings precisa ser objeto")
            override_bytes = cls._render_override(override)
            created.append("override.cfg")
            writes.append(("override.cfg", len(override_bytes)))

        return InstallPlan(
            appid=install.appid, game_name=install.name, game_dir=game_dir, engine=cls.kind,
            target=pack.name, translation_id=translation.id, locale=translation.locale,
            version=translation.version, backups=[pack.name], created=created,
            writes=writes, required_bytes=needed, warnings=warnings,
            payload={
                "pack": pack, "replacements": replacements, "additions": additions,
                "override": override_bytes if apply else b"", "buildid": install.buildid,
                "tool": tool, "gdre": gdre, "key": (params.get("gdre") or {}).get("key"),
            },
        )

    @classmethod
    def _plan_replace(cls, install: GameInstall, game: Game, translation: Translation,
                      artifact_paths: list[Path] | None, apply: bool) -> InstallPlan:
        game_dir = install.path
        detection = detect(game_dir)
        running = safety.processes_running([install.installdir, game_dir.name])
        params = translation.install.get("params") or {}
        pack = cls.resolve_pack(game_dir, params)
        read_pack(pack)
        if len(translation.artifacts) != 1 or translation.artifacts[0].type != "pck":
            raise GodotError("replace_pack exige exatamente um artefato .pck")
        artifact = translation.artifacts[0]

        needed = pack.stat().st_size * 2 + artifact.size
        pre = safety.preflight(game_dir, cls.kind, detection.engine, detection.anticheat,
                               needed, running)
        errors = list(pre.errors)
        catalog_anticheat = list(game.risk.get("anticheat") or [])
        if catalog_anticheat:
            errors.append("catalogo marca anti-cheat: " + ", ".join(catalog_anticheat))
        if game.risk.get("online"):
            errors.append("jogo com componente online: aplicar traducao nao e permitido")
        if errors:
            raise GodotError("; ".join(errors))

        source = None
        if apply:
            if not artifact_paths:
                raise GodotError(f"artefato {artifact.url} nao baixado")
            source = Path(artifact_paths[0])
            if not source.is_file():
                raise GodotError(f"artefato ausente: {source}")
            try:
                read_pack(source)
            except PckError as exc:
                raise GodotError(f"o artefato nao e um pack Godot valido: {exc}") from exc
        writes = [(pack.name, source.stat().st_size if source else artifact.size)]

        return InstallPlan(
            appid=install.appid, game_name=install.name, game_dir=game_dir, engine=cls.kind,
            target=pack.name, translation_id=translation.id, locale=translation.locale,
            version=translation.version, backups=[pack.name], created=[],
            writes=writes, required_bytes=needed,
            warnings=["substitui o pack inteiro; o backup permite reverter"],
            payload={
                "pack": pack, "mode": "replace_pack",
                "artifact": source, "buildid": install.buildid,
                "tool": "tdeck-pack-replace",
            },
        )

    @staticmethod
    def _gdre_binary(params: dict) -> str:
        gdre = params.get("gdre") or {}
        binary = (os.environ.get("TDECK_GDRE_PATH") or gdre.get("path")
                  or shutil.which("gdre_tools") or shutil.which("gdre_tools.exe"))
        if not binary or not Path(binary).is_file():
            raise GodotError(
                "GDRE Tools nao encontrado (TDECK_GDRE_PATH, install.params.gdre.path ou PATH)"
            )
        return str(binary)

    @classmethod
    def _gdre_patch(cls, payload: dict, pack: Path, target: Path) -> None:
        """Patch via GDRE --pck-patch (gera arquivo novo, validado antes do replace)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = [payload["gdre"], "--headless", f"--pck-patch={pack}", f"--output={target}"]
            for index, (path, data) in enumerate(list(payload["replacements"].items())
                                                 + list(payload["additions"])):
                src = Path(tmpdir) / f"p{index}{Path(path).suffix}"
                src.write_bytes(data)
                args.append(f"--patch-file={src}=res://{path.removeprefix('res://')}")
            if payload.get("key"):
                args.append(f"--key={payload['key']}")
            result = subprocess.run(args, capture_output=True, text=True, timeout=600)
            if result.returncode != 0 or not target.is_file():
                detail = (result.stderr or result.stdout).strip().replace("\r", " ")
                raise GodotError(f"GDRE falhou: {detail[-400:]}")

    @classmethod
    def apply(cls, plan: InstallPlan) -> ApplyResult:
        payload = plan.payload
        pack: Path = payload["pack"]
        if payload.get("mode") == "replace_pack":
            return cls._apply_replace(plan)
        with safety.Lock(mf.state_dir() / "locks" / f"{plan.appid}.lock"):
            before = mf.sha256_file(pack)
            backup = mf.backup_file(plan.game_dir, pack.name, plan.appid, payload["buildid"])

            tmp = pack.with_name(pack.name + ".tdeck-new")
            try:
                if payload.get("tool") == "gdre":
                    cls._gdre_patch(payload, pack, tmp)
                else:
                    rewrite_pack(pack, tmp, payload["replacements"], payload["additions"])
                read_pack(tmp)  # valida o pack gerado antes de substituir o original
                os.replace(tmp, pack)
            except (PckError, OSError) as exc:
                tmp.unlink(missing_ok=True)
                raise GodotError(f"falha ao reescrever o pack: {exc}") from exc
            except GodotError:
                tmp.unlink(missing_ok=True)
                raise

            for relpath in plan.created:
                if relpath == "override.cfg":
                    mf.write_atomic(plan.game_dir / relpath, payload["override"])

            files = [mf.InstalledFile(
                relpath=pack.name, backup=str(backup), sha256_before=before,
                sha256_after=mf.sha256_file(pack), size=pack.stat().st_size,
            )]
            for relpath in plan.created:
                files.append(mf.InstalledFile(
                    relpath=relpath, backup=None, sha256_before=None,
                    sha256_after=mf.sha256_file(plan.game_dir / relpath),
                    size=(plan.game_dir / relpath).stat().st_size,
                ))
            mf.save(mf.Manifest(
                appid=plan.appid, translation_id=plan.translation_id, locale=plan.locale,
                version=plan.version, engine=plan.engine, buildid=payload["buildid"],
                installed_at=mf.now_iso(), tool=payload["tool"], files=files,
                created_files=list(plan.created),
            ))
        return ApplyResult(True, mf.STATUS_INSTALLED, "traducao instalada",
                           [f.relpath for f in files])

    @classmethod
    def _apply_replace(cls, plan: InstallPlan) -> ApplyResult:
        payload = plan.payload
        pack: Path = payload["pack"]
        source: Path = payload["artifact"]
        with safety.Lock(mf.state_dir() / "locks" / f"{plan.appid}.lock"):
            before = mf.sha256_file(pack)
            backup = mf.backup_file(plan.game_dir, pack.name, plan.appid, payload["buildid"])
            tmp = pack.with_name(pack.name + ".tdeck-new")
            try:
                shutil.copyfile(source, tmp)
                read_pack(tmp)
                os.replace(tmp, pack)
            except (PckError, OSError) as exc:
                tmp.unlink(missing_ok=True)
                raise GodotError(f"falha ao substituir o pack: {exc}") from exc
            files = [mf.InstalledFile(
                relpath=pack.name, backup=str(backup), sha256_before=before,
                sha256_after=mf.sha256_file(pack), size=pack.stat().st_size,
            )]
            mf.save(mf.Manifest(
                appid=plan.appid, translation_id=plan.translation_id, locale=plan.locale,
                version=plan.version, engine=plan.engine, buildid=payload["buildid"],
                installed_at=mf.now_iso(), tool=payload["tool"], files=files,
                created_files=[],
            ))
        return ApplyResult(True, mf.STATUS_INSTALLED, "traducao instalada (pack substituido)",
                           [pack.name])

    @staticmethod
    def uninstall(appid: int, game_dir: Path) -> ApplyResult:
        current = mf.load(appid)
        if current is None:
            return ApplyResult(False, mf.STATUS_MISSING, "nenhuma traducao instalada")
        with safety.Lock(mf.state_dir() / "locks" / f"{appid}.lock"):
            restored = mf.restore(current, game_dir)
            mf.delete(appid)
        return ApplyResult(True, "removed", "traducao removida", restored)

    @staticmethod
    def verify(appid: int, game_dir: Path) -> ApplyResult:
        current = mf.load(appid)
        if current is None:
            return ApplyResult(False, mf.STATUS_MISSING, "nenhuma traducao instalada")
        status, changed = mf.verify(current, game_dir)
        messages = {
            mf.STATUS_INSTALLED: "traducao instalada e intacta",
            mf.STATUS_REVALIDATED: "a Steam reverteu/alterou arquivos; reaplique a traducao",
            mf.STATUS_MISSING: "arquivos do patch desapareceram",
        }
        return ApplyResult(status == mf.STATUS_INSTALLED, status, messages.get(status, status), changed)


def _render_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        inner = ", ".join(_quote(str(item)) for item in value)
        return f"PackedStringArray({inner})"
    return _quote(str(value))


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def translation_from_json(raw: dict, appid: int | None, translation_id: str | None,
                          source_kind: str) -> tuple[Game, Translation]:
    """Valida um descritor de traducao avulso (fonte manual / sideload)."""
    from ..catalog import validate_game

    raw = dict(raw)
    raw.setdefault("source", {}).setdefault("type", source_kind)
    game = validate_game(raw, where="manual")
    if appid is not None and game.appid != appid:
        raise GodotError(f"appid do descritor ({game.appid}) difere do pedido ({appid})")
    if translation_id is None:
        if len(game.translations) != 1:
            raise GodotError("descritor manual precisa ter exatamente uma traducao")
        return game, game.translations[0]
    for translation in game.translations:
        if translation.id == translation_id:
            return game, translation
    raise GodotError(f"traducao {translation_id!r} ausente no descritor")
