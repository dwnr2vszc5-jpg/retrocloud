"""Game catalog: curated entries from games.json plus ROMs found in per-system folders.

Like a handheld's SD card: a file dropped into RC_ROMS_DIR/<system>/ (e.g. roms/psx/Game.chd)
shows up under that system with the system's default core. ROM paths are resolved strictly
inside RC_ROMS_DIR so a catalog entry or a scanned file can never point outside it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

CORE_RE = r"^[A-Za-z0-9_.-]+_libretro\.so$"
MAX_SCANNED = 5000          # per worker; keeps /api/games cheap on a slow disk
BIOS_DIR = "bios"           # RC_ROMS_DIR/bios/: BIOS files the user owns (never shipped)


class System(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9]{1,16}$")
    name: str
    short: str
    maker: str = ""
    year: int = 0
    core: str = Field(pattern=CORE_RE)
    extensions: list[str]
    bios: list[str] = []


class Game(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    title: str
    system: str
    core: str = Field(pattern=CORE_RE)
    rom: str
    license: str
    notes: str = ""
    source: str = "catalog"   # "catalog" (games.json) | "folder" (found in roms/<system>/)

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


_TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")


def title_from_filename(stem: str) -> str:
    """'Some_Game (USA) [!]' -> 'Some Game'; keeps the raw stem if cleaning empties it."""
    t = _TAGS.sub("", stem.replace("_", " ")).strip()
    return re.sub(r"\s{2,}", " ", t) or stem


def game_id(system: str, rel: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", Path(rel).stem.lower()).strip("-")[:40] or "game"
    h = hashlib.sha1(rel.encode()).hexdigest()[:6]   # stable, and unique for same-named files
    return f"{system}-{slug}-{h}"[:64]


def load_systems(path: Path) -> dict[str, System]:
    if not path.is_file():
        return {}
    return {s["id"]: System(**s) for s in json.loads(path.read_text())}


class Catalog:
    def __init__(self, games_file: Path, roms_dir: Path, cores_dir: Path,
                 systems_file: Path | None = None) -> None:
        self.games_file = games_file
        self.roms_dir = roms_dir
        self.cores_dir = cores_dir
        self.systems = load_systems(systems_file) if systems_file else {}
        raw = json.loads(games_file.read_text())
        self.curated: dict[str, Game] = {g["id"]: Game(**g) for g in raw}
        self.games: dict[str, Game] = dict(self.curated)
        self.rescan()

    # ---------- folder scan ----------
    def _scan_system(self, sysdef: System, budget: list[int]) -> list[Game]:
        root = self.roms_dir / sysdef.id
        if not root.is_dir():
            return []
        exts = {e.lower() for e in sysdef.extensions}
        found: list[Game] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            names = set(filenames)
            for fn in sorted(filenames):
                if budget[0] <= 0:
                    return found
                if fn.startswith("."):
                    continue
                stem, _, ext = fn.rpartition(".")
                ext = ext.lower()
                if not stem or ext not in exts:
                    continue
                # disc images: list the .cue/.m3u, not the .bin tracks it references
                if ext == "bin" and any(f"{stem}.{e}" in names for e in ("cue", "CUE")):
                    continue
                if ext in ("cue", "chd") and f"{stem}.m3u" in names:
                    continue
                # BIOS archives next to arcade sets are not games
                if fn in sysdef.bios:
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fn), self.roms_dir)
                try:
                    safe_join(self.roms_dir, rel)
                except ValueError:
                    continue
                budget[0] -= 1
                found.append(Game(id=game_id(sysdef.id, rel), title=title_from_filename(stem),
                                  system=sysdef.id, core=sysdef.core, rom=rel,
                                  license="user-provided", source="folder"))
        return found

    def rescan(self) -> None:
        games = dict(self.curated)
        known_roms = {g.rom for g in games.values()}
        budget = [MAX_SCANNED]
        for sysdef in self.systems.values():
            for g in self._scan_system(sysdef, budget):
                if g.rom not in known_roms:
                    games[g.id] = g
        self.games = games

    # ---------- lookups ----------
    def get(self, game_id: str) -> Game | None:
        return self.games.get(game_id)

    def rom_path(self, game: Game) -> Path:
        return safe_join(self.roms_dir, game.rom)

    def core_path(self, game: Game) -> Path:
        # core names are validated by CORE_RE (no "/" possible), and the cores dir may hold
        # symlinks into the distro's libretro dir, so do not resolve() them like ROM paths
        return self.cores_dir / game.core

    def bios_dir(self) -> Path:
        return self.roms_dir / BIOS_DIR

    def available(self) -> list[dict]:
        out = []
        for g in self.games.values():
            ok = self.rom_path(g).is_file() and self.core_path(g).is_file()
            sysdef = self.systems.get(g.system)
            out.append({**g.model_dump(), "available": ok,
                        "system_name": sysdef.name if sysdef else g.system})
        return out

    def systems_summary(self) -> list[dict]:
        counts: dict[str, int] = {}
        for g in self.games.values():
            counts[g.system] = counts.get(g.system, 0) + 1
        bios = self.bios_dir()
        out = []
        for s in self.systems.values():
            core_ok = (self.cores_dir / s.core).is_file()
            # any one of the listed files is enough (e.g. one Mega CD region BIOS)
            have = any((bios / b).is_file() or (self.roms_dir / s.id / b).is_file() for b in s.bios)
            missing_bios = [] if have or not s.bios else s.bios
            out.append({**s.model_dump(), "games": counts.get(s.id, 0), "core_installed": core_ok,
                        "missing_bios": missing_bios})
        return out
