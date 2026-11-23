"""saves_watcher.py — слежение за Saves/ в рамках сцены (S3.7; 05 §5.7).

Отличие от watcher.py (S1.3): тот пишет общий лог файл-событий для V3a;
этот модуль — сцено-ориентированный: «какой сейв считать итоговым?».
Правило: новейший .sh2 с mtime > времени старта сцены; стабилизация —
файл не меняется ≥ stable_secs (детект завершения 05 §5.7: процесс игры
завершился → интервал ≥ 90 с стабилен).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SaveCandidate:
    path: Path
    mtime: float
    size: int


def scan_saves(saves_dir: Path, since_ts: float) -> list[SaveCandidate]:
    """Все .sh2 в Saves/ (включая подпапку Restarts/, G16) новее since_ts."""
    out: list[SaveCandidate] = []
    saves_dir = Path(saves_dir)
    if not saves_dir.is_dir():
        return out
    for p in saves_dir.rglob("*.sh2"):
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_mtime > since_ts:
            out.append(SaveCandidate(p, st.st_mtime, st.st_size))
    return sorted(out, key=lambda c: (c.mtime, c.path.name))


def newest_save(saves_dir: Path, since_ts: float) -> SaveCandidate | None:
    cands = scan_saves(saves_dir, since_ts)
    return cands[-1] if cands else None


def wait_for_final_save(saves_dir: Path, since_ts: float,
                        game_process_gone: bool,
                        stable_secs: float = 90.0,
                        poll_interval: float = 2.0,
                        timeout_secs: float = 7200.0) -> SaveCandidate | None:
    """Блокирующее ожидание итогового сейва (детект завершения 05 §5.7).

    Условие готовности: процесс игры завершился (game_process_gone —
    внешний флаг от watchdog) И новейший сейв стабилен stable_secs.
    Возвращает кандидат или None по тайм-ауту. Поллинг poll_interval=2с
    (05 §5.7). Тесты подменяют время через time_fn.
    """
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        cand = newest_save(saves_dir, since_ts)
        if cand is not None and game_process_gone:
            # стабильность: mtime не менялся stable_secs
            if time.time() - cand.mtime >= stable_secs:
                return cand
        time.sleep(poll_interval)
    return None
