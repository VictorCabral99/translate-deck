#!/usr/bin/env python3
"""Empacota o plugin Decky em out/store.zip ou out/sideload.zip."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parent
CORE = REPO / "core" / "src" / "tdeck_core"
OUT = REPO / "out"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def stage(edition: str) -> Path:
    target = OUT / f".staging-{edition}"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)

    for name in ("plugin.json", "package.json", "main.py", "README.md"):
        source = PLUGIN / name
        if source.is_file():
            shutil.copy2(source, target / name)
    shutil.copy2(REPO / "LICENSE", target / "LICENSE")
    if (PLUGIN / "assets").is_dir():
        shutil.copytree(PLUGIN / "assets", target / "assets")

    dist = PLUGIN / "dist"
    if not dist.is_dir() or not any(dist.iterdir()):
        print("erro: plugin/dist vazio; rode `npm install && npm run build` em plugin/",
              file=sys.stderr)
        raise SystemExit(1)
    shutil.copytree(dist, target / "dist")

    shutil.copytree(CORE, target / "py_modules" / "tdeck_core", ignore=IGNORE)

    if edition == "store":
        (target / "manual_wiring.py").unlink(missing_ok=True)
        (target / "py_modules" / "tdeck_core" / "sources" / "manual.py").unlink(missing_ok=True)
        for chunk in (target / "dist").glob("ManualSource-*"):
            chunk.unlink()
    elif not (target / "manual_wiring.py").is_file():
        shutil.copy2(PLUGIN / "manual_wiring.py", target / "manual_wiring.py")
    return target


def pack(staged: Path, destination: Path) -> None:
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staged.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staged).as_posix())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", choices=["store", "sideload"], default="store")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)

    staged = stage(args.edition)
    destination = OUT / f"{args.edition}.zip"
    pack(staged, destination)

    names = zipfile.ZipFile(destination).namelist()
    leaked = [name for name in names if "manual" in name.lower()]
    if args.edition == "store" and leaked:
        print(f"erro: build da loja contem arquivo manual: {leaked}", file=sys.stderr)
        return 1
    if args.edition == "sideload" and not any(
            name.startswith("dist/ManualSource-") and name.endswith(".js") for name in names):
        print("erro: build sideload sem chunk manual; rode `npm run build` em plugin/",
              file=sys.stderr)
        return 1

    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    print(f"{destination} ({len(names)} arquivos)\nsha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
