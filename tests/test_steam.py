from __future__ import annotations

from pathlib import Path

from tdeck_core.steam import (
    GameInstall, SteamError, find_install, find_installs, library_folders, parse_vdf,
    sanitize_installdir, steam_roots,
)

LIBRARY_VDF = '''
"libraryfolders"
{
    "0"
    {
        "path"      "C:/Steam"
        "apps"      { "228980" "123" }
    }
    "1"
    {
        "path"      "Z:/SteamLibrary-que-nao-existe"
    }
}
'''

ACF = '''
"AppState"
{
    "appid"       "367520"
    "name"        "Hollow Knight"
    "installdir"  "Hollow Knight"
    "buildid"     "123456"
    "StateFlags"  "4"
}
'''


def make_library(root: Path, appid: int = 367520, flags: int = 4,
                 installdir: str = "Hollow Knight") -> Path:
    library = root
    (library / "steamapps").mkdir(parents=True, exist_ok=True)
    (library / "steamapps" / "libraryfolders.vdf").write_text(LIBRARY_VDF, encoding="utf-8")
    (library / "steamapps" / f"appmanifest_{appid}.acf").write_text(
        ACF.replace('"4"', f'"{flags}"').replace("Hollow Knight", installdir),
        encoding="utf-8",
    )
    (library / "steamapps" / "common" / installdir).mkdir(parents=True, exist_ok=True)
    return library


def test_parse_vdf_nested_and_escaped():
    data = parse_vdf('"a" { "b" "c" "d" { "e" "f" } } // comentario')
    assert data["a"]["b"] == "c"
    assert data["a"]["d"]["e"] == "f"


def test_library_folders_skips_missing_path(tmp_path: Path):
    root = make_library(tmp_path / "Steam")
    libraries = library_folders(root)
    assert libraries == [root]  # D:/SteamLibrary nao existe


def test_library_folders_includes_second_disk(tmp_path: Path):
    root = make_library(tmp_path / "Steam")
    second = tmp_path / "D" / "SteamLibrary"
    (second / "steamapps").mkdir(parents=True)
    vdf = root / "steamapps" / "libraryfolders.vdf"
    vdf.write_text(LIBRARY_VDF.replace("Z:/SteamLibrary-que-nao-existe", second.as_posix()),
                   encoding="utf-8")
    assert library_folders(root) == [root, second]


def test_find_installs_and_install(tmp_path: Path):
    root = make_library(tmp_path / "Steam")
    installs = find_installs(root)
    assert [(i.appid, i.name, i.buildid) for i in installs] == [(367520, "Hollow Knight", "123456")]
    install = find_install(367520, root)
    assert install is not None and install.installed
    assert install.path == root / "steamapps" / "common" / "Hollow Knight"
    assert find_install(999, root) is None


def test_find_installs_ignores_not_fully_installed(tmp_path: Path):
    make_library(tmp_path / "Steam", flags=2)
    assert find_installs(tmp_path / "Steam") == []


def test_installed_requires_directory(tmp_path: Path):
    root = make_library(tmp_path / "Steam")
    import shutil
    shutil.rmtree(root / "steamapps" / "common" / "Hollow Knight")
    install = GameInstall(appid=1, name="x", installdir="Hollow Knight", library=root,
                          buildid="1", state_flags=4)
    assert not install.installed


def test_steam_root_env_override(tmp_path: Path, monkeypatch):
    root = make_library(tmp_path / "Steam")
    monkeypatch.setenv("STEAM_ROOT", str(root))
    assert steam_roots() == [root]


def test_compatdata_and_prefix(tmp_path: Path):
    root = make_library(tmp_path / "Steam")
    install = find_install(367520, root)
    assert not install.compatdata.exists() and install.proton_prefix is None
    (install.compatdata / "pfx").mkdir(parents=True)
    assert install.proton_prefix == install.compatdata / "pfx"


def test_sanitize_installdir_blocks_traversal():
    assert sanitize_installdir("Hollow Knight") == "Hollow Knight"
    for bad in ("", "..", "../x", "a/b", "a\\b", ".", "x" * 300):
        try:
            sanitize_installdir(bad)
        except SteamError:
            continue
        raise AssertionError(f"aceitou installdir inseguro: {bad!r}")
