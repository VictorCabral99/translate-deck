from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from tdeck_core import manifest as mf, safety


def test_lock_is_exclusive(tmp_path: Path):
    path = tmp_path / "a.lock"
    with safety.Lock(path):
        with pytest.raises(safety.LockError):
            safety.Lock(path).acquire()
    assert not path.exists()
    with safety.Lock(path):
        pass


def test_stale_lock_is_replaced(tmp_path: Path):
    path = tmp_path / "a.lock"
    path.write_text("999 0\n", encoding="utf-8")
    old = time.time() - safety.STALE_SECONDS - 5
    os.utime(path, (old, old))
    with safety.Lock(path) as lock:
        assert lock.path == path
        assert path.exists()


def test_check_space(tmp_path: Path):
    safety.check_space(tmp_path, 1024)
    with pytest.raises(safety.SafetyError, match="espaco insuficiente"):
        safety.check_space(tmp_path, 1 << 62)


def test_preflight_errors_and_warning(tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    free = safety.disk_free(game_dir)

    ok = safety.preflight(game_dir, "godot", "godot", [], 1024)
    assert ok.ok and not ok.errors
    assert ok.warnings == []

    low = safety.preflight(game_dir, "godot", "godot", [], int(free * 0.9))
    assert low.ok and low.warnings and "2x" in low.warnings[0]

    bad = safety.preflight(game_dir, "godot", "unity", ["eac"], 0, running=["Game.exe"])
    assert not bad.ok
    assert any("engine" in e for e in bad.errors)
    assert any("anti-cheat" in e for e in bad.errors)
    assert any("execucao" in e for e in bad.errors)


def test_preflight_missing_dir(tmp_path: Path):
    result = safety.preflight(tmp_path / "nope", "godot", "godot", [], 0)
    assert not result.ok and "nao existe" in result.errors[0]


def test_processes_running_matches_live_process(monkeypatch):
    monkeypatch.setattr(safety.subprocess, "run", lambda *a, **k: type(
        "R", (), {"stdout": '"python.exe","1","Console","1","1 KB"\n'})(), raising=False)
    assert safety.processes_running(["python.exe"]) == ["python.exe"]
    assert safety.processes_running(["nao-existe-xyz"]) == []


def _manifest(tmp_path: Path, name: str = "Game.pck") -> tuple[mf.Manifest, Path]:
    game_dir = tmp_path / "game"
    game_dir.mkdir(exist_ok=True)
    target = game_dir / name
    target.write_bytes(b"original")
    backup = mf.backup_file(game_dir, name, 1, "42")
    manifest = mf.Manifest(
        appid=1, translation_id="t", locale="pt_BR", version="1", engine="godot",
        buildid="42", installed_at=mf.now_iso(), tool="tdeck-pck",
        files=[mf.InstalledFile(relpath=name, backup=str(backup),
                                sha256_before=mf.sha256_file(target),
                                sha256_after=mf.sha256_file(target), size=6)],
        created_files=[],
    )
    return manifest, game_dir


def test_backup_restore_and_verify(tmp_path: Path):
    manifest, game_dir = _manifest(tmp_path)
    target = game_dir / "Game.pck"

    assert mf.verify(manifest, game_dir)[0] == mf.STATUS_INSTALLED
    target.write_bytes(b"modificado")
    status, changed = mf.verify(manifest, game_dir)
    assert status == mf.STATUS_REVALIDATED and changed == ["Game.pck"]

    target.unlink()
    assert mf.verify(manifest, game_dir)[0] == mf.STATUS_MISSING

    target.write_bytes(b"modificado")
    restored = mf.restore(manifest, game_dir)
    assert restored == ["Game.pck"] and target.read_bytes() == b"original"


def test_restore_removes_created_files(tmp_path: Path):
    manifest, game_dir = _manifest(tmp_path)
    override = game_dir / "override.cfg"
    override.write_bytes(b"[x]")
    manifest.created_files = ["override.cfg"]
    mf.restore(manifest, game_dir)
    assert not override.exists()


def test_manifest_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TDECK_HOME", str(tmp_path / "state"))
    manifest, _ = _manifest(tmp_path)
    mf.save(manifest)
    loaded = mf.load(1)
    assert loaded is not None and loaded.translation_id == "t" and loaded.buildid == "42"
    assert mf.manifest_path(1).is_file()
    mf.delete(1)
    assert mf.load(1) is None


def test_prune_backups(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TDECK_HOME", str(tmp_path / "state"))
    manifest, _ = _manifest(tmp_path)
    mf.save(manifest)
    backup = Path(manifest.files[0].backup)
    assert mf.prune_backups(keep_days=30) == []
    assert backup.is_file()
