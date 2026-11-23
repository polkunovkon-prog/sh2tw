"""Подсистема K6 — GA-конвейер доктрин (ТЗ 08 §8.7–8.9; S6.1–S6.4).

Движок (run_ga по алгоритму ТЗ), фитнес (08 §8.8), пул прогонов
(Scripted/SemiAuto-источники, Sandboxie-заглушка) и полуавтоматический CLI.
"""
from .engine import (DEFAULT_GA_CONFIG, GENES, GaError, GeneSpec, crossover,
                     genome_to_doctrine, load_ga_config, mutate,
                     random_genome, run_ga)
from .fitness import aggregate, fitness
from .runner_pool import (HEARTBEAT_STALE_SEC, MEM_LIMIT_MB, InstancePool,
                          MatchRunner, ScriptedSource, SemiAutoSource,
                          stable_seed)

__all__ = [
    "DEFAULT_GA_CONFIG", "GENES", "GaError", "GeneSpec", "crossover",
    "genome_to_doctrine", "load_ga_config", "mutate", "random_genome",
    "run_ga", "aggregate", "fitness", "HEARTBEAT_STALE_SEC", "MEM_LIMIT_MB",
    "InstancePool", "MatchRunner", "ScriptedSource", "SemiAutoSource",
    "stable_seed",
]
