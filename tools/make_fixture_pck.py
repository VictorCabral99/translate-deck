"""Gera um fixture .pck sintetico para os testes (sem precisar do Godot)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core" / "src"))

from tdeck_core import pck  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures/fixture.pck")
    out.parent.mkdir(parents=True, exist_ok=True)
    info = pck.create_pack(
        out,
        {
            "res://scenes/menu.tscn": b"[gd_scene format=3]\n",
            "res://locale/en.translation": b"EN\0\0fake-translation",
            "res://audio/theme.ogg": b"OggS" + b"\x00" * 256,
        },
        layout="godot3",
    )
    print(f"{out} ({len(info.entries)} entradas, layout {info.layout})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
