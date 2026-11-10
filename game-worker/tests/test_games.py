import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from worker.games import Catalog, Game, safe_join
from worker.input import BUTTON_KEYSYMS, BUTTON_ORDER
from worker.session import RETROARCH_CFG

ROOT = Path(__file__).resolve().parent.parent


def test_safe_join_blocks_traversal(tmp_path: Path) -> None:
    (tmp_path / "roms").mkdir()
    assert safe_join(tmp_path / "roms", "a/b.nes") == (tmp_path / "roms" / "a" / "b.nes").resolve()
    for bad in ("../x.nes", "a/../../x", "/etc/passwd"):
        with pytest.raises(ValueError):
            safe_join(tmp_path / "roms", bad)


def test_safe_join_blocks_symlink_escape(tmp_path: Path) -> None:
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "evil").symlink_to("/etc")
    with pytest.raises(ValueError):
        safe_join(roms, "evil/passwd")


@pytest.mark.parametrize("field,value", [("rom", "../x.nes"), ("rom", "/abs.nes"), ("core", "../../bin/sh"),
                                          ("id", "Bad Id"), ("core", "nestopia.so")])
def test_game_model_rejects_bad_values(field: str, value: str) -> None:
    g = {"id": "ok", "title": "t", "system": "nes", "core": "nestopia_libretro.so", "rom": "a.nes", "license": "MIT"}
    g[field] = value
    with pytest.raises(ValidationError):
        Game(**g)


def test_catalog_loads_and_testpad_rom_present() -> None:
    cat = Catalog(ROOT / "config" / "games.json", ROOT / "roms", Path("/nonexistent"))
    g = cat.get("testpad")
    assert g is not None and cat.rom_path(g).is_file()
    assert cat.available()[0]["available"] is False  # core dir missing -> not available


def test_button_mapping_consistent_across_layers() -> None:
    """worker/input.py, retroarch.cfg template and web/player.js must agree on buttons."""
    js = (ROOT / "web" / "player.js").read_text()
    order = json.loads("[" + re.search(r"const ORDER = \[(.*?)\];", js).group(1) + "]")
    assert order == BUTTON_ORDER
    cfg = RETROARCH_CFG
    x_to_ra = {"Up": "up", "Down": "down", "Left": "left", "Right": "right", "Return": "enter", "Shift_R": "rshift"}
    for button, keysym in BUTTON_KEYSYMS.items():
        assert f'input_player1_{button} = "{x_to_ra.get(keysym, keysym)}"' in cfg


def test_hotkeys_disabled() -> None:
    for hk in ("input_exit_emulator", "input_menu_toggle", "input_save_state", "input_load_state"):
        assert f'{hk} = "nul"' in RETROARCH_CFG


# ---------------- per-system folders (R36S-style roms/<system>/) ----------------
def _cat(tmp_path: Path) -> Catalog:
    games = tmp_path / "games.json"
    games.write_text("[]")
    return Catalog(games, tmp_path / "roms", tmp_path / "cores", ROOT / "config" / "systems.json")


def test_systems_file_is_valid() -> None:
    from worker.games import load_systems
    systems = load_systems(ROOT / "config" / "systems.json")
    assert {"nes", "snes", "gb", "gba", "md", "psx", "arcade"} <= set(systems)
    for s in systems.values():
        assert s.extensions and all(e == e.lower() and "." not in e for e in s.extensions)


def test_folder_scan_finds_games_and_hides_disc_tracks(tmp_path: Path) -> None:
    roms = tmp_path / "roms"
    for rel in ("nes/Some_Game (USA).nes", "nes/readme.txt", "psx/Disc Game/Disc Game.cue",
                "psx/Disc Game/Disc Game (Track 1).bin", "psx/Disc Game/Disc Game.bin",
                "psx/Other.chd", "neogeo/neogeo.zip", "neogeo/mslug.zip", "nes/.hidden.nes"):
        (roms / rel).parent.mkdir(parents=True, exist_ok=True)
        (roms / rel).write_bytes(b"x")
    cat = _cat(tmp_path)
    by_rom = {g.rom: g for g in cat.games.values()}
    assert set(by_rom) == {"nes/Some_Game (USA).nes", "psx/Disc Game/Disc Game.cue", "psx/Other.chd",
                           "neogeo/mslug.zip"}
    g = by_rom["nes/Some_Game (USA).nes"]
    assert g.title == "Some Game" and g.core == "nestopia_libretro.so" and g.source == "folder"
    assert re.fullmatch(r"nes-some-game-usa-[0-9a-f]{6}", g.id)
    # ids are stable between scans
    assert cat.get(g.id) is not None
    cat.rescan()
    assert cat.get(g.id).rom == g.rom


def test_folder_scan_ignores_symlink_escape(tmp_path: Path) -> None:
    roms = tmp_path / "roms"
    (roms / "nes").mkdir(parents=True)
    outside = tmp_path / "outside.nes"
    outside.write_bytes(b"x")
    (roms / "nes" / "evil.nes").symlink_to(outside)
    assert _cat(tmp_path).games == {}


def test_systems_summary_reports_missing_bios(tmp_path: Path) -> None:
    (tmp_path / "roms").mkdir()
    cat = _cat(tmp_path)
    summary = {s["id"]: s for s in cat.systems_summary()}
    assert summary["neogeo"]["missing_bios"] == ["neogeo.zip"]
    assert summary["psx"]["missing_bios"] == []          # PCSX ReARMed has an HLE BIOS
    (tmp_path / "roms" / "bios").mkdir()
    (tmp_path / "roms" / "bios" / "bios_CD_E.bin").write_bytes(b"x")
    assert {s["id"]: s for s in cat.systems_summary()}["segacd"]["missing_bios"] == []


def test_core_symlinks_into_distro_dir_are_allowed(tmp_path: Path) -> None:
    distro = tmp_path / "usr-lib-libretro"
    distro.mkdir()
    (distro / "nestopia_libretro.so").write_bytes(b"x")
    cores = tmp_path / "cores"
    cores.mkdir()
    (cores / "nestopia_libretro.so").symlink_to(distro / "nestopia_libretro.so")
    (tmp_path / "roms" / "nes").mkdir(parents=True)
    (tmp_path / "roms" / "nes" / "a.nes").write_bytes(b"x")
    cat = _cat(tmp_path)
    assert [g["available"] for g in cat.available()] == [True]


def test_handheld_style_folder_names_are_recognised(tmp_path: Path) -> None:
    roms = tmp_path / "roms"
    for rel in ("megadrive/Game A.md", "genesis/Game B.gen", "mastersystem/C.sms", "fbneo/d.zip"):
        (roms / rel).parent.mkdir(parents=True, exist_ok=True)
        (roms / rel).write_bytes(b"x")
    by_sys: dict[str, list[str]] = {}
    for g in _cat(tmp_path).games.values():
        by_sys.setdefault(g.system, []).append(g.rom)
    assert sorted(by_sys["md"]) == ["genesis/Game B.gen", "megadrive/Game A.md"]
    assert by_sys["sms"] == ["mastersystem/C.sms"] and by_sys["arcade"] == ["fbneo/d.zip"]
