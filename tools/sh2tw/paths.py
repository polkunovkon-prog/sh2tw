"""Загрузка config/project.ini (контракт 03 §3.12; ключи репозитория S0.0)."""
from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INI = REPO_ROOT / "config" / "project.ini"


@dataclass(frozen=True)
class Paths:
    game_dir: Path
    maps_dir_game: Path
    maps_dir_user: Path
    saves_dir: Path
    backup_dir: Path
    exe: Path

    @property
    def exe_path(self) -> Path:
        return self.game_dir / self.exe.name if self.exe else self.game_dir


def load_paths(ini: Path | None = None) -> Paths:
    cp = configparser.ConfigParser(interpolation=configparser.BasicInterpolation())
    cp.read(ini or DEFAULT_INI, encoding="utf-8")
    p = cp["paths"]
    return Paths(
        game_dir=Path(p["game_dir"]),
        maps_dir_game=Path(p["maps_dir_game"]),
        maps_dir_user=Path(p["maps_dir_user"]),
        saves_dir=Path(p["saves_dir"]),
        backup_dir=Path(p["backup_dir"]),
        exe=Path(p.get("exe", "Stronghold2.exe")),
    )
