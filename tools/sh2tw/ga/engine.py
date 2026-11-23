"""engine.py — GA-движок доктрин (S6.1; 08 §8.3, §8.7 — алгоритм из ТЗ).

Псевдокод 08 §8.7: стартовая популяция — мутанты сида (удвоенная сигма),
поколения: evaluate (внешняя функция) → фитнес → hall_of_fame (top-10) →
лог population_gen_<N>.json → стоп по plateau/generations_max → элитизм 2 +
равномерное скрещивание потомков от турнирного отбора k=3 → мутация (элита
не мутирует — иначе элитизм теряет смысл). Сиды записываются в run_log.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Callable

import yaml

from ..doctrines.archetypes import ARCHETYPES
from ..doctrines.choreography import invasion_plan
from ..doctrines.doctrine import DoctrineError, GENOME_SPEC, validate_genome
from ..paths import REPO_ROOT
from .fitness import fitness

HALL_OF_FAME_SIZE = 10


class GaError(Exception):
    """Ошибка GA-конвейера (конфиг, геном, контракт evaluate)."""


DEFAULT_GA_CONFIG: dict = {
    "population": 12,
    "generations_max": 20,
    "matches_per_candidate": 3,
    "defenses_portfolio": ["def_hedgehog", "def_archers", "def_killer_walls"],
    "selection": {"kind": "tournament", "k": 3},
    "elitism": 2,
    "mutation": {"sigma_rel": 0.15, "gene_prob": 0.3},
    "crossover": "uniform",
    "speed": "x3",
    "instances": 2,
    "stop": {"winrate_plateau_generations": 5},
    "time_budget_hours_per_generation": 2,
}


@dataclass(frozen=True)
class GeneSpec:
    """Спецификация одного гена (08 §8.3): границы и тип."""

    name: str
    kind: str                    # int | float | enum | bool
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()


def _spec_to_gene(name: str, spec: dict) -> GeneSpec:
    return GeneSpec(name=name, kind=spec["kind"],
                    minimum=spec.get("min"), maximum=spec.get("max"),
                    choices=tuple(spec.get("choices", ())))


# Канон границ — doctrines/doctrine.py GENOME_SPEC (08 §8.3), порядок стабилен.
GENES: list[GeneSpec] = [_spec_to_gene(n, s) for n, s in GENOME_SPEC.items()]


def load_ga_config(path: Path | None = None) -> dict:
    """Конфиг GA из YAML (по умолчанию ga_config.yaml в корне репо)."""
    p = Path(path) if path is not None else REPO_ROOT / "ga_config.yaml"
    if not p.is_file():
        return dict(DEFAULT_GA_CONFIG)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise GaError(f"конфиг GA {p}: ожидался объект")
    return data


def _effective_config(cfg: dict) -> dict:
    """DEFAULT + пользовательский cfg (двухуровневое слияние секций)."""
    if not isinstance(cfg, dict):
        raise GaError("cfg: объект (ga_config.yaml)")
    eff = {**DEFAULT_GA_CONFIG, **cfg}
    for key in ("selection", "mutation", "stop"):
        merged = dict(DEFAULT_GA_CONFIG[key])
        merged.update(cfg.get(key) or {})
        eff[key] = merged
    return eff


def random_genome(rng: random.Random) -> dict:
    """Случайный валидный геном (границы GENOME_SPEC)."""
    if not isinstance(rng, random.Random):
        raise GaError("rng: random.Random (детерминизм)")
    out: dict = {}
    for gene in GENES:
        if gene.kind == "int":
            out[gene.name] = rng.randint(int(gene.minimum), int(gene.maximum))
        elif gene.kind == "float":
            out[gene.name] = round(
                gene.minimum + rng.random() * (gene.maximum - gene.minimum), 6)
        elif gene.kind == "enum":
            out[gene.name] = rng.choice(list(gene.choices))
        else:
            out[gene.name] = rng.random() < 0.5
    return out


def mutate(genome: dict, cfg: dict, rng: random.Random,
           sigma_rel: float | None = None) -> dict:
    """Гауссова мутация: sigma = sigma_rel×диапазон, вероятность на ген 0.3.

    Вход обязан быть полным валидным геномом (validate_genome); клампы
    удерживают значения в границах, int-гены округляются (08 §8.3).
    """
    mut = (cfg.get("mutation") or {}) if isinstance(cfg, dict) else {}
    gene_prob = float(mut.get("gene_prob", 0.3))
    sr = float(sigma_rel if sigma_rel is not None
               else mut.get("sigma_rel", 0.15))
    out = dict(genome)
    for gene in GENES:
        if rng.random() >= gene_prob:
            continue
        cur = out[gene.name]
        if gene.kind == "int":
            span = gene.maximum - gene.minimum
            v = int(round(float(cur) + rng.gauss(0.0, sr * span)))
            out[gene.name] = max(int(gene.minimum), min(int(gene.maximum), v))
        elif gene.kind == "float":
            span = gene.maximum - gene.minimum
            v = float(cur) + rng.gauss(0.0, sr * span)
            out[gene.name] = round(
                max(gene.minimum, min(gene.maximum, v)), 6)
        elif gene.kind == "enum":
            out[gene.name] = rng.choice(list(gene.choices))
        else:  # bool
            out[gene.name] = not cur
    return out


def crossover(a: dict, b: dict, rng: random.Random | None = None) -> dict:
    """Равномерное скрещивание по генам; без rng — чередование (детерминизм)."""
    if set(a) != set(b):
        raise GaError("crossover: геномы с разными наборами генов")
    if rng is None:
        return {name: (a[name] if i % 2 == 0 else b[name])
                for i, name in enumerate(GENOME_SPEC)}
    return {name: (a[name] if rng.random() < 0.5 else b[name])
            for name in GENOME_SPEC}


def _tournament(pop: list[dict], fits: list[float], rng: random.Random,
                k: int) -> dict:
    """Турнирный отбор: k случайных особей, лучшая по фитнесу проходит."""
    best_i = rng.randrange(len(pop))
    for _ in range(max(1, k) - 1):
        i = rng.randrange(len(pop))
        if fits[i] > fits[best_i]:
            best_i = i
    return pop[best_i]


def _result_fitness(result: dict) -> float:
    """Фитнес результата evaluate: aggregate (fitness_mean) или один матч."""
    if isinstance(result, dict) and "fitness_mean" in result:
        return float(result["fitness_mean"])
    return fitness(result)


def _mean_finite(values: list[float]) -> float | None:
    finite = [v for v in values if math.isfinite(v)]
    return sum(finite) / len(finite) if finite else None


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                               default=str), encoding="utf-8")


def _fingerprint(rng: random.Random) -> str:
    """Стабильный отпечаток состояния rng (сиды записываются, 08 §8.7)."""
    blob = repr(rng.getstate()).encode("utf-8")
    return sha256(blob).hexdigest()[:16]


def run_ga(cfg: dict, evaluate: Callable[[dict], dict], rng: random.Random,
           *, seed_genome: dict | None = None, run_id: str = "ga_run",
           run_root: Path | str | None = None) -> dict:
    """Прогон GA (08 §8.7) → {"champion", "run_log"}.

    evaluate(genome) → матч (win/time_min/losses_pct/breakthrough/wall_abuse/
    honesty_violations) ИЛИ агрегат fitness.aggregate ({"fitness_mean", ...}).
    Стоп: plateau (нет улучшения лучшего фитнеса N поколений) или generations_max.
    """
    if not callable(evaluate):
        raise GaError("evaluate: функция(genome) → результат матча/агрегат")
    if not isinstance(rng, random.Random):
        raise GaError("rng: random.Random (детерминизм прогонов)")
    eff = _effective_config(cfg)
    pop_size = int(eff["population"])
    elitism = int(eff["elitism"])
    plateau_gens = int(eff["stop"]["winrate_plateau_generations"])
    tour_k = int(eff["selection"]["k"])
    if eff["selection"]["kind"] != "tournament":
        raise GaError("selection.kind: поддержан только tournament (08 §8.7)")
    if eff["crossover"] != "uniform":
        raise GaError("crossover: поддержано только uniform (08 §8.7)")
    if pop_size < 2:
        raise GaError("population ≥ 2")
    if not 0 <= elitism < pop_size:
        raise GaError(f"elitism 0..{pop_size - 1}")
    if plateau_gens < 1:
        raise GaError("stop.winrate_plateau_generations ≥ 1")
    try:
        seed = validate_genome(dict(seed_genome) if seed_genome
                               else random_genome(rng))
    except DoctrineError as exc:
        raise GaError(f"сид-геном невалиден: {exc}") from exc

    run_dir = (Path(run_root) if run_root is not None
               else Path("ga_runs")) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint(rng)
    # ТЗ §8.7: стартовая популяция — мутации сида с sigma=0.3 (2× рабочей 0.15)
    sigma0 = float(eff["mutation"]["sigma_rel"]) * 2.0
    pop = [mutate(seed, eff, rng, sigma_rel=sigma0)
           for _ in range(pop_size)]

    hall: list[dict] = []
    generations: list[dict] = []
    best_fitness = -math.inf
    plateau = 0
    stopped = "generations_max"
    for gen in range(int(eff["generations_max"])):
        results = [evaluate(g) for g in pop]
        fits = [_result_fitness(r) for r in results]
        order = sorted(range(len(pop)), key=lambda i: fits[i], reverse=True)
        for i in order:
            hall.append({"genome": pop[i], "fitness": fits[i],
                         "result": results[i], "generation": gen})
        hall = sorted(hall, key=lambda h: h["fitness"],
                      reverse=True)[:HALL_OF_FAME_SIZE]
        gen_log = {
            "generation": gen,
            "population": [{"genome": g, "fitness": f, "result": r}
                           for g, f, r in zip(pop, fits, results)],
            "best_fitness": max(fits),
            "mean_fitness": _mean_finite(fits),
        }
        generations.append(gen_log)
        _write_json(run_dir / f"population_gen_{gen:03d}.json", gen_log)
        if max(fits) > best_fitness:
            best_fitness, plateau = max(fits), 0
        else:
            plateau += 1
        if plateau >= plateau_gens:
            stopped = "plateau"
            break
        elite = [pop[i] for i in order[:elitism]]
        children = []
        while len(children) < pop_size - elitism:
            parent_a = _tournament(pop, fits, rng, tour_k)
            parent_b = _tournament(pop, fits, rng, tour_k)
            children.append(crossover(parent_a, parent_b, rng))
        # элита проходит в следующее поколение без мутаций
        pop = elite + [mutate(c, eff, rng) for c in children]

    champion = dict(hall[0]) if hall else None
    run_log = {
        "run_id": run_id,
        "rng_fingerprint": fingerprint,
        "config": eff,
        "generations_run": len(generations),
        "stopped_reason": stopped,
        "best_fitness": best_fitness if math.isfinite(best_fitness) else None,
        "generations": generations,
        "hall_of_fame": hall,
        "champion": champion,
    }
    _write_json(run_dir / "run_log.json", run_log)
    if champion is not None:
        _write_json(run_dir / "champion.json", champion)
    return {"champion": champion, "run_log": run_log}


def genome_to_doctrine(genome: dict, archetype: str, *, generation: int = 0,
                       parents: list[str] | None = None) -> dict:
    """Геном + архетип → доктрина (контракт doctrine.yaml, S5.6)."""
    if archetype not in ARCHETYPES:
        raise GaError(f"архетип {archetype!r} ∉ {sorted(ARCHETYPES)}")
    try:
        g = validate_genome(genome)
    except DoctrineError as exc:
        raise GaError(f"геном невалиден: {exc}") from exc
    plan = invasion_plan(archetype, g)
    waves = [e for e in plan if "troops" in e and "action" not in e]
    return {
        "doctrine_id": f"doc_{archetype}_ga_g{generation}",
        "version": 1,
        "archetype": archetype,
        "aic_file": f"templates/doctrines/aic_{archetype}_ga.aic",
        "gamerules_patch": None,
        "invasion_choreography": waves,
        "genome": g,
        "provenance": {"origin": "ga", "generation": int(generation),
                       "parents": list(parents or []),
                       "evaluated_matches": 0, "winrate": 0.0,
                       "honesty_violations": 0},
    }
