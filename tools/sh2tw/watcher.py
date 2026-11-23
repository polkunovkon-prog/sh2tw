"""S1.3: watcher папки Saves/ — поллинг 2 с + лог файл-событий (для V3a и раннера K3).

Чистое ядро (snapshot/diff) тестируется без треда; watch() — обёртка с интервалом.
Событие = строка JSON: {"t": iso, "event": created|modified|deleted, "name", "path", "size"}.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

POLL_S = 2.0


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if p.is_file():
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_mtime_ns, st.st_size)
    return out


def diff(prev: dict[str, tuple[int, int]], cur: dict[str, tuple[int, int]]) -> list[dict]:
    ev: list[dict] = []
    for name, (mt, size) in cur.items():
        if name not in prev:
            ev.append({"event": "created", "name": name, "size": size})
        elif prev[name] != (mt, size):
            ev.append({"event": "modified", "name": name, "size": size})
    for name in prev:
        if name not in cur:
            ev.append({"event": "deleted", "name": name, "size": None})
    return sorted(ev, key=lambda e: e["name"])


def watch(root: Path, on_event, interval: float = POLL_S,
          stop: threading.Event | None = None, duration_s: float | None = None):
    """Поллинг root; на каждое событие — on_event(event_dict). Возвращает число событий."""
    prev = snapshot(root)
    n = 0
    t0 = time.monotonic()
    stop = stop or threading.Event()
    while not stop.is_set():
        time.sleep(interval)
        cur = snapshot(root)
        for e in diff(prev, cur):
            e["t"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            e["path"] = str(root / e["name"])
            on_event(e)
            n += 1
        prev = cur
        if duration_s is not None and time.monotonic() - t0 >= duration_s:
            break
    return n


def jsonl_logger(out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fh = out_path.open("a", encoding="utf-8")

    def _log(e: dict):
        fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        fh.flush()

    _log.fh = fh  # type: ignore[attr-defined]
    return _log
