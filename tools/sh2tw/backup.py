"""S1.1: бэкап Maps/ (протокол 00 §63) и Saves/.

Инвариант: перед первым запуском кода, меняющего Maps/, обязателен реальный
(не dry-run) бекап. Сухой режим только печатает манифест.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .paths import Paths


@dataclass
class Entry:
    src: Path
    size: int


def collect(src_root: Path, patterns: tuple[str, ...] = ("*",)) -> list[Entry]:
    if not src_root.is_dir():
        return []
    out: list[Entry] = []
    for pat in patterns:
        for f in src_root.rglob(pat):
            if f.is_file():
                out.append(Entry(f, f.stat().st_size))
    # дедуп по пути (перекрывающиеся глобы), стабильный порядок
    seen: set[str] = set()
    uniq = []
    for e in sorted(out, key=lambda e: str(e.src)):
        if str(e.src) not in seen:
            seen.add(str(e.src))
            uniq.append(e)
    return uniq


def _plan_backup(paths: Paths, src_root: Path, dest_sub: str, stamp: str,
                 patterns: tuple[str, ...] = ("*",)) -> tuple[Path, list[Entry]]:
    dest = paths.backup_dir / f"{dest_sub}_{stamp}"
    return dest, collect(src_root, patterns)


def run_backup(paths: Paths, dry_run: bool = False,
               what: tuple[str, ...] = ("maps", "saves")) -> dict:
    """Возвращает резюме: {dest: [src,...]} или манифест для dry_run."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    summary: dict = {"stamp": stamp, "dry_run": dry_run, "targets": {}}
    jobs = []
    if "maps" in what:
        jobs.append(("maps_game", paths.maps_dir_game, ("*",), "maps_game"))
        jobs.append(("maps_user", paths.maps_dir_user, ("*",), "maps_user"))
    if "saves" in what:
        jobs.append(("saves", paths.saves_dir, ("*",), "saves"))
    for name, src_root, patterns, dest_sub in jobs:
        entries = collect(src_root, patterns)
        dest = paths.backup_dir / f"{dest_sub}_{stamp}"
        total = sum(e.size for e in entries)
        summary["targets"][name] = {
            "src": str(src_root), "dest": str(dest),
            "files": len(entries), "bytes": total,
        }
        if dry_run:
            continue
        dest.mkdir(parents=True, exist_ok=True)
        for e in entries:
            rel = e.src.relative_to(src_root)
            tgt = dest / rel
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(e.src, tgt)
    return summary
