from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from tdeck_core import pck


@pytest.fixture()
def pack(tmp_path: Path) -> Path:
    target = tmp_path / "Game.pck"
    pck.create_pack(target, {
        "res://scenes/menu.tscn": b"scene-bytes",
        "res://locale/en.translation": b"EN|hello",
        "res://audio/theme.ogg": b"OggS" + bytes(range(64)),
    }, layout="godot3")
    return target


def test_read_pack_entries(pack: Path):
    info = pck.read_pack(pack)
    assert info.layout == "godot3"
    assert info.engine == (3, 5, 3)
    assert [e.norm_path for e in info.entries] == [
        "scenes/menu.tscn", "locale/en.translation", "audio/theme.ogg",
    ]
    assert [e.norm_path for e in info.translation_entries] == ["locale/en.translation"]


@pytest.mark.parametrize("layout", ["godot3", "godot4", "godot44"])
def test_create_and_read_layouts(tmp_path: Path, layout: str):
    target = tmp_path / f"{layout}.pck"
    pck.create_pack(target, {"res://a.txt": b"a", "res://b.bin": b"\x00\x01"}, layout=layout)
    info = pck.read_pack(target)
    assert info.layout == layout
    assert pck.extract(target, "res://a.txt", info) == b"a"


def test_rewrite_v4_roundtrip(tmp_path: Path):
    pack = tmp_path / "v4.pck"
    pck.create_pack(pack, {
        "res://scenes/menu.tscn": b"scene-bytes",
        "res://locale/en.translation": b"EN|hello",
    }, layout="godot44", engine=(4, 4, 0))
    info = pck.rewrite_pack(
        pack, tmp_path / "new.pck",
        replacements={"res://locale/en.translation": b"PT|ola"},
        additions=[("res://locale/pt_BR.translation", b"PT|ola")],
    )
    assert info.format_version == 4
    rewritten = pck.read_pack(tmp_path / "new.pck")
    assert rewritten.layout == "godot44"
    assert pck.extract(tmp_path / "new.pck", "res://locale/en.translation", rewritten) == b"PT|ola"
    assert pck.extract(tmp_path / "new.pck", "res://locale/pt_BR.translation", rewritten) == b"PT|ola"
    assert pck.extract(tmp_path / "new.pck", "res://scenes/menu.tscn", rewritten) == b"scene-bytes"


def test_refuses_entry_flags(pack: Path, tmp_path: Path):
    info = pck.read_pack(pack)
    info.entries[0].flags = 1
    with pytest.raises(pck.PckError, match="flags"):
        pck._check_rewritable(info)
    info.entries[0].flags = 0
    info.pack_flags = pck.PACK_DIR_ENCRYPTED
    with pytest.raises(pck.PckError, match="criptografado"):
        pck._check_rewritable(info)


def test_embedded_pack_detection_v4(tmp_path: Path):
    exe = tmp_path / "game.exe"
    pck_target = tmp_path / "Game.pck"
    pck.create_pack(pck_target, {"res://a.txt": b"a"}, layout="godot44", engine=(4, 4, 0))
    exe.write_bytes(b"MZ" + b"\x00" * 128 + pck_target.read_bytes())
    offset = pck.find_embedded_pack(exe)
    assert offset == 130
    info = pck.read_pack(exe, header_offset=offset)
    assert pck.extract(exe, "res://a.txt", info) == b"a"


def test_embedded_pack_trailer(tmp_path: Path):
    exe = tmp_path / "game.exe"
    pck_target = tmp_path / "Game.pck"
    pck.create_pack(pck_target, {"res://a.txt": b"a"}, layout="godot44", engine=(4, 4, 0))
    payload = pck_target.read_bytes()
    exe.write_bytes(b"MZ" + b"\x00" * 128 + payload
                    + struct.pack("<Q", len(payload)) + b"GDPC")
    offset = pck.find_embedded_pack(exe)
    assert offset == 130
    info = pck.read_pack(exe, header_offset=offset)
    assert pck.extract(exe, "res://a.txt", info) == b"a"


def test_extract_matches_md5(pack: Path):
    info = pck.read_pack(pack)
    entry = info.find("res://audio/theme.ogg")
    data = pck.extract(pack, entry, info)
    assert hashlib.md5(data).digest() == entry.md5


def test_rewrite_replaces_and_adds(tmp_path: Path, pack: Path):
    new_content = b"PT-BR|ola mundo"
    info = pck.rewrite_pack(
        pack, tmp_path / "new.pck",
        replacements={"res://locale/en.translation": new_content},
        additions=[("res://locale/pt_BR.translation", new_content)],
    )
    assert len(info.entries) == 4
    rewritten = pck.read_pack(tmp_path / "new.pck")
    assert pck.extract(tmp_path / "new.pck", "res://locale/en.translation", rewritten) == new_content
    assert pck.extract(tmp_path / "new.pck", "res://locale/pt_BR.translation", rewritten) == new_content
    assert pck.extract(tmp_path / "new.pck", "res://scenes/menu.tscn", rewritten) == b"scene-bytes"


def test_rewrite_preserves_untouched_md5(pack: Path, tmp_path: Path):
    before = pck.read_pack(pack)
    pck.rewrite_pack(pack, tmp_path / "new.pck", additions=[("res://x.txt", b"x")])
    after = pck.read_pack(tmp_path / "new.pck")
    for entry in before.entries:
        assert after.find(entry.path).md5 == entry.md5


def test_rewrite_rejects_duplicate_addition(pack: Path, tmp_path: Path):
    with pytest.raises(pck.PckError):
        pck.rewrite_pack(pack, tmp_path / "new.pck",
                         additions=[("res://locale/en.translation", b"x")])


def test_read_rejects_non_pck(tmp_path: Path):
    target = tmp_path / "fake.pck"
    target.write_bytes(b"NOPE" + b"\x00" * 64)
    with pytest.raises(pck.PckError):
        pck.read_pack(target)


def test_embedded_pack_detection(tmp_path: Path):
    exe = tmp_path / "game.exe"
    pck_target = tmp_path / "Game.pck"
    pck.create_pack(pck_target, {"res://a.txt": b"a"})
    payload = pck_target.read_bytes()
    exe.write_bytes(b"MZ" + b"\x00" * 128 + payload)
    offset = pck.find_embedded_pack(exe)
    assert offset == 130
    with pytest.raises(pck.PckError):
        pck.rewrite_pack(exe, tmp_path / "out.pck", additions=[("res://b.txt", b"b")])
