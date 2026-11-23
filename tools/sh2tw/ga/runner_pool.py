"""runner_pool.py — пул прогонов матчей GA (S6.3; 08 §8.9).

Реальный запуск игры в этой среде НЕ реализован (honest-граница):
ScriptedSource — детерминированный псевдо-исход для тестов/сухих прогонов
("simulated": true); SemiAutoSource — ввод человеком через ga_cli
(match_result_<id>.json). Sandboxie-пул — только имена профилей и учёт
занятости, без запуска процессов. Watchdog-лимиты — реюз ..runner.watchdog.
"""
from __future__ import annotations

import json
import random
from hashlib import sha256
from pathlib import Path

from ..runner.watchdog import HEARTBEAT_STALE_SEC, MEM_LIMIT_MB


def stable_seed(value) -> str:
    """Стабильный межпроцессно отпечаток значения → сид матча."""
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return sha256(blob.encode("utf-8")).hexdigest()[:16]


class ScriptedSource:
    """Детерминированный псевдо-исход матча (для тестов; simulated)."""

    def __init__(self, win_probability: float = 0.5, seed: int = 0):
        if not 0.0 <= float(win_probability) <= 1.0:
            raise ValueError("win_probability: 0..1")
        self.win_probability = float(win_probability)
        self.seed = int(seed)

    def resolve(self, context: dict) -> dict:
        rng = random.Random(
            f"scripted:{self.seed}:{context.get('seed')}:"
            f"{context.get('defense_id')}")
        win = rng.random() < self.win_probability
        return {
            "win": win,
            "outcome": "W" if win else "L",
            "time_min": round(15.0 + 45.0 * rng.random(), 1),
            "losses_pct": round(rng.random() * 0.8, 3),
            "breakthrough": rng.random() < 0.35,
            "wall_abuse": 0,
            "honesty_violations": 0,
            "aborted": False,
            "simulated": True,
        }


class SemiAutoSource:
    """Исход от человека: ga_cli result → match_result_<id>.json (08 §8.9)."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)

    def resolve(self, context: dict) -> dict:
        path = self.run_dir / f"match_result_{context.get('match_id')}.json"
        if not path.is_file():
            return {"status": "pending_human", "aborted": False, "win": None,
                    "honesty_violations": 0, "simulated": False}
        data = json.loads(path.read_text(encoding="utf-8"))
        outcome = str(data.get("outcome", "L")).upper()
        attacker = int(data.get("attacker_losses", 0) or 0)
        defender = int(data.get("defender_losses", 0) or 0)
        total = attacker + defender
        # оценка доли потерь атакующего от суммарных потерь матча; точная доля
        # от отправленных войск считается при наличии росписи волн (S5.4)
        losses_pct = round(attacker / total, 3) if total > 0 else 0.0
        return {
            "win": outcome == "W",
            "outcome": outcome,
            "draw": outcome == "D",
            "time_min": None,
            "losses_pct": losses_pct,
            "breakthrough": False,
            "wall_abuse": 0,
            "honesty_violations": 0,
            "aborted": False,
            "simulated": False,
            "source": "human",
            "attacker_losses": attacker,
            "defender_losses": defender,
        }


class MatchRunner:
    """Прогон одного матча кандидата против обороны (интерфейс, 08 §8.9)."""

    def __init__(self, source):
        self.source = source

    def run_match(self, candidate_genome: dict, defense_id: str,
                  match_id: str | None = None) -> dict:
        """Матч → dict, совместимый с match_result.json и fitness.aggregate.

        Реальный запуск игры — вне этой среды (заглушка launcher); aborted-
        матч не идёт в зачёт (aggregate пропускает, 08 §8.9).
        """
        seed = stable_seed(candidate_genome)
        context = {"match_id": match_id, "defense_id": defense_id,
                   "seed": seed}
        outcome = self.source.resolve(context)
        return {
            "match_id": match_id,
            "defense_id": defense_id,
            "seed": seed,
            "watchdog": {"memory_limit_mb": MEM_LIMIT_MB,
                         "heartbeat_stale_sec": HEARTBEAT_STALE_SEC},
            "launcher": "not_implemented_in_this_environment",
            **outcome,
        }


class InstancePool:
    """Слоты инстансов игры (Sandboxie-профили, 08 §8.9) — honest-заглушка.

    Реальный запуск Sandboxie-профилей в этой среде не реализован: пул
    ведёт только имена профилей и занятость слотов.
    """

    def __init__(self, profiles: list[str] | None = None,
                 instances: int = 2):
        if profiles:
            names = list(profiles)
        else:
            names = [f"S2TW_GA_{i + 1}" for i in range(max(1, int(instances)))]
        if not names:
            raise ValueError("InstancePool: нужен ≥1 профиль")
        self.profiles = names
        self._busy: set[str] = set()

    def acquire(self) -> str | None:
        """Занять свободный слот; None — все заняты."""
        for profile in self.profiles:
            if profile not in self._busy:
                self._busy.add(profile)
                return profile
        return None

    def release(self, profile: str) -> bool:
        """Освободить слот; True — слот был занят."""
        if profile in self._busy:
            self._busy.discard(profile)
            return True
        return False

    @property
    def free(self) -> list[str]:
        return [p for p in self.profiles if p not in self._busy]

    def as_dict(self) -> dict:
        return {"profiles": list(self.profiles),
                "busy": sorted(self._busy),
                "free": list(self.free),
                "sandboxie": "stub: реальный запуск Sandboxie-профилей "
                             "в этой среде не реализован (08 §8.9)"}
