"""Подсистема K5 — библиотека доктрин ИИ (ТЗ 08, этап 5; S5.2–S5.6).

Архетипы .aic (клоны+правки / честный синтез), хореографии вторжений,
контракт doctrine.yaml и дифф-протокол 50 general values.
"""
from .aic_diff import cluster_report, general_values_matrix, matrix_to_csv
from .archetypes import (ARCHETYPES, ARCHETYPE_TRANSFORMS, SYNTHETIC_WARNING,
                         DoctrineError, build_archetype_aic,
                         build_archetype_aic_result, load_base_aic,
                         write_archetypes)
from .choreography import invasion_plan
from .doctrine import (GENOME_SPEC, build_doctrine, doctrine_for_persona,
                       doctrine_scene_events, load_doctrine, save_doctrine,
                       validate_doctrine, validate_genome)

__all__ = [
    "ARCHETYPES", "ARCHETYPE_TRANSFORMS", "SYNTHETIC_WARNING", "DoctrineError",
    "build_archetype_aic", "build_archetype_aic_result", "load_base_aic",
    "write_archetypes", "invasion_plan", "GENOME_SPEC", "build_doctrine",
    "doctrine_for_persona", "doctrine_scene_events", "load_doctrine",
    "save_doctrine", "validate_doctrine", "validate_genome",
    "cluster_report", "general_values_matrix", "matrix_to_csv",
]
