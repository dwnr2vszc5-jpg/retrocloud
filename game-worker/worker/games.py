"""Game catalog: a JSON file listing games whose ROMs we are allowed to run.

ROM paths are resolved strictly inside RC_ROMS_DIR so a catalog entry (or a
future upload feature) can never point at an arbitrary file on the host.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class Game(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    title: str
    system: str
    core: str = Field(pattern=r"^[A-Za-z0-9_.-]+_libretro\.so$")
    rom: str
    license: str
    notes: str = ""

    @field_validator("rom")
    @classmethod
    def _relative(cls, v: str) -> str:
        p = Path(v)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError("rom must be a relative path inside the ROM directory")
        return v


def safe_join(base: Path, rel: str) -> Path:
    """Resolve rel under base and refuse anything that escapes it (path traversal, symlinks)."""
    base_r = base.resolve()
    target = (base_r / rel).resolve()
    if base_r != target and base_r not in target.parents:
        raise ValueError(f"path escapes {base_r}")
    return target


class Catalog:
    def __init__(self, games_file: Path, roms_dir: Path, cores_dir: Path) -> None:
        self.roms_dir = roms_dir
        self.cores_dir = cores_dir
        raw = json.loads(games_file.read_text())
        self.games: dict[str, Game] = {g["id"]: Game(**g) for g in raw}

    def get(self, game_id: str) -> Game | None:
        return self.games.get(game_id)

    def rom_path(self, game: Game) -> Path:
        return safe_join(self.roms_dir, game.rom)

    def core_path(self, game: Game) -> Path:
        return safe_join(self.cores_dir, game.core)

    def available(self) -> list[dict]:
        out = []
        for g in self.games.values():
            ok = self.rom_path(g).is_file() and self.core_path(g).is_file()
            out.append({**g.model_dump(), "available": ok})
        return out
