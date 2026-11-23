"""watchdog.py — краш-контроль процесса игры (S3.7; ТЗ 05 §5.7).

Правила: игра упала (код возврата ≠ 0 или процесс исчез до конца сцены) —
сцена помечается aborted, crash-лог (время, код) в scene_result.anomalies;
армия игрока возвращается без потерь («правило милосердия», 07 §7.7).
Память: psutil есть — меряем (лимит 1.6 ГБ, 08 §8.9); psutil нет — None
(модуль не обязателен, 00 §0.5).
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

MEM_LIMIT_MB = 1600.0  # 08 §8.9: память > 1.6 ГБ → рестарт инстанса
HEARTBEAT_STALE_SEC = 180.0  # нет heartbeat 3 мин → зависание (08 §8.9)


@dataclass
class WatchdogState:
    running: bool
    returncode: int | None = None
    mem_mb: float | None = None
    heartbeat_age_sec: float | None = None
    events: list[str] = field(default_factory=list)

    @property
    def crashed(self) -> bool:
        return (not self.running and self.returncode not in (0, None)) or \
            (self.mem_mb is not None and self.mem_mb > MEM_LIMIT_MB)

    @property
    def hung(self) -> bool:
        return self.heartbeat_age_sec is not None and self.heartbeat_age_sec > HEARTBEAT_STALE_SEC

    def as_dict(self) -> dict:
        return {"running": self.running, "returncode": self.returncode,
                "mem_mb": self.mem_mb,
                "heartbeat_age_sec": self.heartbeat_age_sec,
                "crashed": self.crashed, "hung": self.hung,
                "events": self.events}


def check_process(proc: subprocess.Popen | None) -> WatchdogState:
    """Снимок состояния процесса: жив ли, код возврата, память."""
    if proc is None:
        return WatchdogState(running=False, returncode=None,
                             events=["процесс не запускался"])
    rc = proc.poll()
    running = rc is None
    mem_mb: float | None = None
    if running:
        try:
            import psutil
            mem_mb = psutil.Process(proc.pid).memory_info().rss / (1024 * 1024)
        except ImportError:
            mem_mb = None
        except Exception:
            mem_mb = None  # процесс мог завершиться между poll и замером
    return WatchdogState(running=running, returncode=rc, mem_mb=mem_mb)


def heartbeat_age(bridge_dir: Path) -> float | None:
    """Возраст heartbeat.json моста (сек); файла нет — None (мост выключен)."""
    p = Path(bridge_dir) / "heartbeat.json"
    if not p.exists():
        return None
    try:
        return max(0.0, time.time() - p.stat().st_mtime)
    except OSError:
        return None


def watchdog_report(proc: subprocess.Popen | None,
                    bridge_dir: Path | None = None) -> dict:
    """Итоговый рапорт watchdog для scene_result.anomalies (05 §5.7)."""
    st = check_process(proc)
    hb = heartbeat_age(Path(bridge_dir)) if bridge_dir else None
    st.heartbeat_age_sec = hb
    if st.crashed:
        st.events.append(f"краш: код {st.returncode}, память {st.mem_mb} МБ — "
                         f"сцена aborted, армия без потерь (милосердие 07 §7.7)")
    if st.hung:
        st.events.append(f"heartbeat молчит {hb:.0f} с — зависание, рестарт "
                         f"инстанса (08 §8.9)")
    return st.as_dict()
