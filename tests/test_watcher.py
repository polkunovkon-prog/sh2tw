"""Тесты S1.3: чистый diff-центр + интеграционный прогон watch() на tmp-дереве."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from sh2tw.watcher import diff, snapshot, watch


def test_diff_created_modified_deleted():
    a = {"x.sh2": (100, 10), "y.sh2": (200, 20)}
    b = {"x.sh2": (150, 11), "z.sh2": (300, 30)}
    ev = diff(a, b)
    kinds = {e["name"]: e["event"] for e in ev}
    assert kinds == {"x.sh2": "modified", "z.sh2": "created", "y.sh2": "deleted"}


def test_diff_empty_to_empty():
    assert diff({}, {}) == []


def test_watch_detects_new_file(tmp_path: Path):
    sub = tmp_path / "Saves"
    sub.mkdir()
    events: list[dict] = []
    stop = threading.Event()
    th = threading.Thread(target=watch, args=(sub, events.append),
                          kwargs={"interval": 0.05, "stop": stop}, daemon=True)
    th.start()
    time.sleep(0.12)
    f = sub / "auto_save_1.sh2"
    f.write_bytes(b"123")
    time.sleep(0.2)
    stop.set()
    th.join(timeout=1)
    assert len(events) == 1
    e = events[0]
    assert e["event"] == "created" and e["name"] == "auto_save_1.sh2" and e["size"] == 3
    assert "t" in e  # временная метка есть


def test_watch_detects_mtime_touch_same_size(tmp_path: Path):
    sub = tmp_path / "Saves"
    sub.mkdir()
    f = sub / "a.sh2"
    f.write_bytes(b"aaa")
    events: list[dict] = []
    stop = threading.Event()
    th = threading.Thread(target=watch, args=(sub, events.append),
                          kwargs={"interval": 0.05, "stop": stop}, daemon=True)
    th.start()
    time.sleep(0.12)
    import os
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    time.sleep(0.2)
    stop.set()
    th.join(timeout=1)
    assert len(events) == 1 and events[0]["event"] == "modified"
