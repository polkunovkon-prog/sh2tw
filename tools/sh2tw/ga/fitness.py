"""fitness.py — фитнес доктрины по матчам (S6.2; 08 §8.8 дословно).

F = 100×Win − 0.5×T_min − 30×Losses_pct + 15×Breakthrough − 20×WallAbuse;
honesty_violations > 0 → F = −∞ (матч в карантин, доктрина в карантин).
Losses_pct — доля 0..1 (35% → 0.35): множитель 30 согласован с Win=100.
Итог по набору матчей — лексикографический: честность → победы → время →
потери (lex_key, меньше = лучше); aborted-матчи в зачёт не идут (08 §8.9).
"""
from __future__ import annotations

WIN_BONUS = 100.0
TIME_COEF = 0.5
LOSSES_COEF = 30.0
BREAKTHROUGH_BONUS = 15.0
WALL_ABUSE_PENALTY = 20.0


def _wall_abuse_value(v) -> float:
    """WallAbuse: bool → 0/1, число — как есть (счётчик эпизодов)."""
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    try:
        return float(max(0, int(v)))
    except (TypeError, ValueError):
        return 0.0


def fitness(match: dict) -> float:
    """Фитнес одного матча (08 §8.8); нарушение честности → −∞."""
    if not isinstance(match, dict):
        raise ValueError(f"match: словарь, факт {type(match).__name__}")
    if int(match.get("honesty_violations", 0) or 0) > 0:
        return float("-inf")
    win = 1.0 if match.get("win") else 0.0
    time_min = float(match.get("time_min") or 0.0)
    losses = float(match.get("losses_pct") or 0.0)
    breakthrough = 1.0 if match.get("breakthrough") else 0.0
    return (WIN_BONUS * win - TIME_COEF * time_min - LOSSES_COEF * losses
            + BREAKTHROUGH_BONUS * breakthrough
            - WALL_ABUSE_PENALTY * _wall_abuse_value(match.get("wall_abuse", 0)))


def aggregate(matches: list[dict]) -> dict:
    """Лексикографический итог набора матчей (08 §8.8).

    honest → wins → время → потери; ключи: fitness_mean (−∞ при нарушениях),
    wins, honesty_violations, quarantined, aborted, lex_key (список, меньше =
    лучше: [нарушения>0, −wins, time_mean, losses_mean]).
    """
    if not isinstance(matches, list):
        raise ValueError("matches: список")
    counted: list[dict] = []
    aborted: list[dict] = []
    for m in matches:
        if isinstance(m, dict) and m.get("aborted"):
            aborted.append(m)  # abort-политика: не в зачёт (08 §8.9)
        else:
            counted.append(m)
    quarantined = [m for m in counted
                   if int(m.get("honesty_violations", 0) or 0) > 0]
    clean = [m for m in counted
             if int(m.get("honesty_violations", 0) or 0) <= 0]
    violations = sum(int(m.get("honesty_violations", 0) or 0) for m in counted)
    wins = sum(1 for m in clean if m.get("win"))
    if violations > 0:
        fitness_mean = float("-inf")
    elif clean:
        fitness_mean = sum(fitness(m) for m in clean) / len(clean)
    else:
        fitness_mean = 0.0  # нет зачётных матчей — нейтральный ноль
    times = [float(m.get("time_min") or 0.0) for m in clean]
    losses = [float(m.get("losses_pct") or 0.0) for m in clean]
    time_mean = sum(times) / len(times) if times else None
    losses_mean = sum(losses) / len(losses) if losses else None
    lex_key = [1 if violations > 0 else 0, -wins,
               time_mean if time_mean is not None else 1e9,
               losses_mean if losses_mean is not None else 1e9]
    return {"matches": len(clean), "wins": wins,
            "honesty_violations": violations,
            "quarantined": quarantined, "aborted": aborted,
            "fitness_mean": fitness_mean, "time_mean": time_mean,
            "losses_mean": losses_mean, "lex_key": lex_key}
