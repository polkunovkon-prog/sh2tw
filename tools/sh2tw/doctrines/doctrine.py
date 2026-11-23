"""doctrine.py — контракт doctrine.yaml: валидация, load/save, сборка (S5.6).

Контракт 03 §3.7 и диапазоны генома 08 §8.3. GENOME_SPEC — единый источник
границ для валидации здесь и для генов GA (ga/engine.py GENES). Нарушение —
DoctrineError; посторонние ключи запрещены (антигаллюцинационный протокол).
"""
from __future__ import annotations

import random
import re
from pathlib import Path

import yaml

from ..scenes.event_dsl import (MAX_TROOPS_PER_TYPE, EventDslError,
                                compile_record, scene_events)
from .archetypes import ARCHETYPES, DoctrineError
from .choreography import invasion_plan

BREACH_TARGETS = ("gate", "wall")
PROVENANCE_ORIGINS = ("manual", "ga")
PROVENANCE_KEYS = ("origin", "generation", "parents", "evaluated_matches",
                   "winrate", "honesty_violations")
TOP_KEYS = ("doctrine_id", "version", "archetype", "aic_file",
            "gamerules_patch", "invasion_choreography", "genome", "provenance")
# Волна плана (формат invasion_plan, S5.4); спец-события — {"action","params"}.
WAVE_KEYS = {"after_months", "troops", "from_marker", "attack_marker", "repeat"}
_DOCTRINE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")  # snake_case ASCII (03 §0.5)

# Геном доктрины (08 §8.3): 23 гена контракта 03 §3.7; границы — канон
# для ga/engine.GENES. Порядок стабилен.
GENOME_SPEC: dict[str, dict] = {
    "first_attack_month": {"kind": "int", "min": 6, "max": 30},
    "wave_count": {"kind": "int", "min": 1, "max": 5},
    "wave_gap_months": {"kind": "int", "min": 2, "max": 10},
    "wave_size_base": {"kind": "int", "min": 8, "max": 40},
    "composition_melee_share": {"kind": "float", "min": 0.3, "max": 0.8},
    "composition_ranged_share": {"kind": "float", "min": 0.15, "max": 0.5},
    "siege_ram": {"kind": "int", "min": 0, "max": 3},
    "siege_tower": {"kind": "int", "min": 0, "max": 2},
    "siege_catapult": {"kind": "int", "min": 0, "max": 4},
    "siege_ladders": {"kind": "int", "min": 0, "max": 8},
    "breach_target": {"kind": "enum", "choices": list(BREACH_TARGETS)},
    "feint_enabled": {"kind": "bool"},
    "feint_ratio": {"kind": "float", "min": 0.1, "max": 0.3},
    "reserve_ratio": {"kind": "float", "min": 0.0, "max": 0.4},
    "retreat_threshold": {"kind": "float", "min": 0.2, "max": 0.6},
    "super_aggressive": {"kind": "bool"},
    "aic_key": {"kind": "enum", "choices": list(ARCHETYPES)},
    "economy_first": {"kind": "bool"},
    "defense_group_archers": {"kind": "float", "min": 0.2, "max": 0.8},
    "recruit_priority_ranged": {"kind": "int", "min": 0, "max": 10},
    "recruit_priority_melee": {"kind": "int", "min": 0, "max": 10},
    "recruit_priority_siege": {"kind": "int", "min": 0, "max": 10},
    "recruit_priority_defense": {"kind": "int", "min": 0, "max": 10},
}


def validate_genome(genome: dict) -> dict:
    """Валидация генома (08 §8.3) → канонический словарь."""
    if not isinstance(genome, dict):
        raise DoctrineError("genome: объект (словарь)")
    unknown = set(genome) - set(GENOME_SPEC)
    if unknown:
        raise DoctrineError(f"genome: неизвестные гены {sorted(unknown)} "
                            f"(антигаллюцинационный протокол)")
    missing = set(GENOME_SPEC) - set(genome)
    if missing:
        raise DoctrineError(f"genome: отсутствуют гены {sorted(missing)}")
    out: dict = {}
    for name, spec in GENOME_SPEC.items():
        v = genome[name]
        where = f"genome.{name}"
        if spec["kind"] == "int":
            if not isinstance(v, int) or isinstance(v, bool):
                raise DoctrineError(f"{where}: ожидалось целое, факт {v!r}")
            if not spec["min"] <= v <= spec["max"]:
                raise DoctrineError(
                    f"{where}: {v} вне {spec['min']}..{spec['max']} (08 §8.3)")
            out[name] = v
        elif spec["kind"] == "float":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise DoctrineError(f"{where}: ожидалось число, факт {v!r}")
            fv = float(v)
            if not spec["min"] <= fv <= spec["max"]:
                raise DoctrineError(
                    f"{where}: {fv} вне {spec['min']}..{spec['max']} (08 §8.3)")
            out[name] = fv
        elif spec["kind"] == "bool":
            if not isinstance(v, bool):
                raise DoctrineError(f"{where}: ожидалось true/false, факт {v!r}")
            out[name] = v
        else:  # enum
            if v not in spec["choices"]:
                raise DoctrineError(
                    f"{where}: {v!r} ∉ {spec['choices']} (08 §8.3)")
            out[name] = v
    return out


def _validate_provenance(prov) -> dict:
    """Валидация блока provenance (03 §3.7)."""
    if not isinstance(prov, dict):
        raise DoctrineError("provenance: объект")
    unknown = set(prov) - set(PROVENANCE_KEYS)
    if unknown:
        raise DoctrineError(f"provenance: неизвестные ключи {sorted(unknown)}")
    missing = set(PROVENANCE_KEYS) - set(prov)
    if missing:
        raise DoctrineError(f"provenance: отсутствуют {sorted(missing)}")
    if prov["origin"] not in PROVENANCE_ORIGINS:
        raise DoctrineError(
            f"provenance.origin: {prov['origin']!r} ∉ {PROVENANCE_ORIGINS}")
    for key in ("generation", "evaluated_matches", "honesty_violations"):
        v = prov[key]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise DoctrineError(f"provenance.{key}: целое ≥ 0, факт {v!r}")
    if not isinstance(prov["parents"], list) or \
            any(not isinstance(p, str) for p in prov["parents"]):
        raise DoctrineError("provenance.parents: список строк (id родителей)")
    wr = prov["winrate"]
    if isinstance(wr, bool) or not isinstance(wr, (int, float)) \
            or not 0.0 <= float(wr) <= 1.0:
        raise DoctrineError(f"provenance.winrate: доля 0..1, факт {wr!r}")
    return {"origin": prov["origin"], "generation": prov["generation"],
            "parents": list(prov["parents"]),
            "evaluated_matches": prov["evaluated_matches"],
            "winrate": float(wr),
            "honesty_violations": prov["honesty_violations"]}


def _validate_choreography(entries) -> list[dict]:
    """Валидация invasion_choreography: волны и спец-события S5.4."""
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise DoctrineError("invasion_choreography: список элементов плана")
    out: list[dict] = []
    for i, el in enumerate(entries):
        where = f"invasion_choreography[{i}]"
        if not isinstance(el, dict):
            raise DoctrineError(f"{where}: объект")
        if "action" in el:  # спец-событие немедленной формы DSL (05 §5.4)
            unknown = set(el) - {"action", "params"}
            if unknown:
                raise DoctrineError(f"{where}: неизвестные ключи {sorted(unknown)}")
            try:
                compile_record({"action": el["action"],
                                "params": el.get("params") or {}}, i)
            except EventDslError as exc:
                raise DoctrineError(f"{where}: {exc}") from exc
            out.append(el)
            continue
        # волна вторжения (формат invasion_plan, S5.4)
        unknown = set(el) - WAVE_KEYS
        if unknown:
            raise DoctrineError(f"{where}: неизвестные ключи {sorted(unknown)}")
        months = el.get("after_months")
        if not isinstance(months, int) or isinstance(months, bool) or months < 1:
            raise DoctrineError(f"{where}.after_months: целое ≥ 1")
        troops = el.get("troops")
        if not isinstance(troops, dict) or not troops:
            raise DoctrineError(f"{where}.troops: {{тип: число}} непусто")
        for utype, count in troops.items():
            if not isinstance(utype, str) or not _DOCTRINE_ID_RE.match(utype):
                raise DoctrineError(f"{where}.troops: тип {utype!r} не snake_case")
            if not isinstance(count, int) or isinstance(count, bool) \
                    or not 1 <= count <= MAX_TROOPS_PER_TYPE:
                raise DoctrineError(
                    f"{where}.troops.{utype}: целое 1..{MAX_TROOPS_PER_TYPE}")
        for key in ("from_marker", "attack_marker"):
            if key in el and (not isinstance(el[key], int)
                              or isinstance(el[key], bool)
                              or not 1 <= el[key] <= 8):
                raise DoctrineError(f"{where}.{key}: маркер 1..8")
        if "repeat" in el and not isinstance(el["repeat"], bool):
            raise DoctrineError(f"{where}.repeat: true/false")
        out.append(el)
    return out


def validate_doctrine(d) -> dict:
    """Полная валидация доктрины → канонический словарь (03 §3.7)."""
    if not isinstance(d, dict):
        raise DoctrineError("doctrine: объект")
    unknown = set(d) - set(TOP_KEYS)
    if unknown:
        raise DoctrineError(f"doctrine: неизвестные ключи {sorted(unknown)}")
    missing = set(TOP_KEYS) - set(d)
    if missing:
        raise DoctrineError(f"doctrine: отсутствуют ключи {sorted(missing)}")
    did = d["doctrine_id"]
    if not isinstance(did, str) or not _DOCTRINE_ID_RE.match(did):
        raise DoctrineError(f"doctrine_id: snake_case, факт {did!r}")
    version = d["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise DoctrineError(f"version: целое ≥ 1, факт {version!r}")
    if d["archetype"] not in ARCHETYPES:
        raise DoctrineError(
            f"archetype: {d['archetype']!r} ∉ {sorted(ARCHETYPES)} (08 §8.4)")
    if not isinstance(d["aic_file"], str) or not d["aic_file"]:
        raise DoctrineError("aic_file: непустая строка (путь шаблона)")
    grp = d["gamerules_patch"]
    if grp is not None and not isinstance(grp, (str, dict)):
        raise DoctrineError("gamerules_patch: null | строка | объект")
    return {
        "doctrine_id": did, "version": version, "archetype": d["archetype"],
        "aic_file": d["aic_file"], "gamerules_patch": grp,
        "invasion_choreography": _validate_choreography(
            d["invasion_choreography"]),
        "genome": validate_genome(d["genome"]),
        "provenance": _validate_provenance(d["provenance"]),
    }


def load_doctrine(path: Path) -> dict:
    """Загрузить doctrine.yaml → валидированный словарь."""
    p = Path(path)
    if not p.is_file():
        raise DoctrineError(f"файл доктрины не найден: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DoctrineError(f"YAML не читается: {exc}") from exc
    if data is None:
        raise DoctrineError("doctrine.yaml пуст")
    return validate_doctrine(data)


def save_doctrine(d: dict, path: Path) -> Path:
    """Валидировать и записать доктрину в YAML (round-trip без потерь)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    canon = validate_doctrine(d)
    p.write_text(yaml.safe_dump(canon, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")
    return p


def default_genome(archetype_id: str) -> dict:
    """Геном по умолчанию архетипа: тайминги/состав/осада — из профиля
    (08 §8.4), прочие гены — нейтральные значения контракта 03 §3.7."""
    if archetype_id not in ARCHETYPES:
        raise DoctrineError(
            f"неизвестный архетип {archetype_id!r}; доступны: "
            f"{', '.join(sorted(ARCHETYPES))} (08 §8.4)")
    prof = ARCHETYPES[archetype_id]
    mix = prof["siege_mix"]
    return validate_genome({
        "first_attack_month": prof["first_attack_month"],
        "wave_count": prof["wave_count"],
        "wave_gap_months": prof["wave_gap_months"],
        "wave_size_base": prof["wave_size_base"],
        "composition_melee_share": prof["melee_share"],
        "composition_ranged_share": prof["ranged_share"],
        "siege_ram": int(mix.get("ram", 0)),
        "siege_tower": int(mix.get("tower", 0)),
        "siege_catapult": int(mix.get("catapult", 0)),
        "siege_ladders": int(mix.get("ladders", 0)),
        "breach_target": "gate",
        "feint_enabled": False,
        "feint_ratio": 0.2,
        "reserve_ratio": 0.2,
        "retreat_threshold": 0.35,
        "super_aggressive": False,
        "aic_key": archetype_id,
        "economy_first": True,
        "defense_group_archers": 0.5,
        "recruit_priority_ranged": 5,
        "recruit_priority_melee": 5,
        "recruit_priority_siege": 3,
        "recruit_priority_defense": 4,
    })


def build_doctrine(archetype_id: str, genome: dict | None = None) -> dict:
    """Полная доктрина архетипа (03 §3.7): invasion_choreography
    заполняется из invasion_plan(archetype, геном доктрины)."""
    g = default_genome(archetype_id)
    if genome:
        g.update(genome)
    g = validate_genome(g)
    return {
        "doctrine_id": f"doc_{archetype_id}_v1",
        "version": 1,
        "archetype": archetype_id,
        "aic_file": f"templates/doctrines/aic_{archetype_id}_v1.aic",
        "gamerules_patch": None,
        "invasion_choreography": invasion_plan(archetype_id, g),
        "genome": g,
        "provenance": {"origin": "manual", "generation": 0, "parents": [],
                       "evaluated_matches": 0, "winrate": 0.0,
                       "honesty_violations": 0},
    }


def _builder_weight(archetype_id: str) -> float:
    """Вес «строителя» (S5.6): hedgehog/fortress 1, sieger 0.6, прочие 0.3."""
    if archetype_id in ("hedgehog", "fortress"):
        return 1.0
    if archetype_id == "sieger":
        return 0.6
    return 0.3


def _greed_weight(archetype_id: str) -> float:
    """Вес «жадины» (S5.6): balanced 1, raider 0.6, прочие 0.3."""
    if archetype_id == "balanced":
        return 1.0
    if archetype_id == "raider":
        return 0.6
    return 0.3


def doctrine_for_persona(persona: dict, rng: random.Random) -> str:
    """doctrine_id из persona.doctrine_pool под черты персоны (07 §7.3).

    score(arch) = aggression×(1/first_month_норм) + builder×строительный вес
    + greed×экономический вес; first_month_норм = first/30 (месяцы 6–30,
    08 §8.3). rng.random() — тай-брейк равных счетов. Возвращает
    doc_<arch>_v1.
    """
    if not isinstance(rng, random.Random):
        raise DoctrineError("rng: random.Random (детерминизм выбора)")
    p = persona or {}
    pool = p.get("doctrine_pool")
    if not isinstance(pool, list) or not pool:
        raise DoctrineError("persona.doctrine_pool: непустой список архетипов")
    weights: dict[str, float] = {}
    for key in ("aggression", "builder", "greed"):
        v = p.get(key, 0.0)
        weights[key] = float(v) if isinstance(v, (int, float)) \
            and not isinstance(v, bool) else 0.0
    best_id, best_score = None, None
    for arch in pool:
        if arch not in ARCHETYPES:
            raise DoctrineError(
                f"persona.doctrine_pool: неизвестный архетип {arch!r} "
                f"(08 §8.4)")
        prof = ARCHETYPES[arch]
        first_norm = prof["first_attack_month"] / 30.0
        score = (weights["aggression"] * (1.0 / first_norm)
                 + weights["builder"] * _builder_weight(arch)
                 + weights["greed"] * _greed_weight(arch)
                 + rng.random() * 1e-6)  # тай-брейк
        if best_score is None or score > best_score:
            best_id, best_score = arch, score
    return f"doc_{best_id}_v1"


def doctrine_scene_events(doctrine: dict, sides: list[dict],
                          duration_months: int = 40) -> list[dict]:
    """mission_events сцены из доктрины (S5.6): база scene_events("siege")
    + волны доктрины как Invasion-элементы (owner — атакующий лорд)
    + спец-события немедленной формы (AITroopRetreat и др.)."""
    canon = validate_doctrine(doctrine)
    plan = invasion_plan(canon["archetype"], canon["genome"])
    events = list(scene_events("siege", sides, duration_months))
    attacker = next((s for s in sides if s.get("role") == "attacker"),
                    sides[0])
    owner = str(attacker.get("lord") or "")
    for el in plan:
        if "action" in el:
            events.append({"action": el["action"],
                           "params": dict(el["params"])})
        else:
            events.append({
                "after_months": el["after_months"],
                "action": "Invasion",
                "params": {"owner": owner,
                           "from_marker": el.get("from_marker", 1),
                           "attack_marker": el.get("attack_marker", 2),
                           "troops": dict(el["troops"]),
                           "repeat": bool(el.get("repeat", False))},
            })
    return events
