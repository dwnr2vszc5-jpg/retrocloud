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
