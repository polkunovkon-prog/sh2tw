"""Тесты доктрин ИИ (S5.2–S5.6; бриф B).

Инварианты: synthetic-режим честно помечен и валиден по формату .aic;
клон правит только документированные поля записей (kind донжонов и
general values не трогаются); хореография совместима с event_dsl;
контракт doctrine.yaml строго валидирует диапазоны 08 §8.3.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from sh2tw.doctrines.aic_diff import (cluster_report, general_values_matrix,
                                      matrix_to_csv)
from sh2tw.doctrines.archetypes import (ARCHETYPES, SYNTHETIC_WARNING,
                                        DoctrineError, build_archetype_aic,
                                        build_archetype_aic_result,
                                        load_base_aic, write_archetypes)
from sh2tw.doctrines.choreography import MELEE_POOL, RANGED_POOL, invasion_plan
from sh2tw.doctrines.doctrine import (GENOME_SPEC, build_doctrine,
                                      doctrine_for_persona,
                                      doctrine_scene_events, load_doctrine,
                                      save_doctrine, validate_doctrine,
                                      validate_genome)
from sh2tw.formats.aic import SIZE_BASE, AicBuildEntry, AicFile
from sh2tw.scenes.event_dsl import compile_events, scene_events

# kind донжонов архетипов (08 §8.4; AIC.md: 20 деревянный/21 малый/
# 22 средний/23 большой) и первый месяц атаки из брифа.
KEEP_KIND = {"hedgehog": 22, "archer": 21, "sieger": 21, "raider": 20,
             "balanced": 22, "fortress": 23}
FIRST_MONTH = {"hedgehog": 26, "archer": 14, "sieger": 18, "raider": 8,
               "balanced": 16, "fortress": 26}
WAVE_KEYS = {"after_months", "troops", "from_marker", "attack_marker",
             "repeat"}


def w0(kind: int, x: int, z: int, rot: int = 0) -> int:
    return (kind & 0xFF) | (x << 8) | (z << 16) | (rot << 24)


def w1(group: int, param: int, high: int = 0) -> int:
    return (group & 0xFFFF) | (param << 16) | (high << 24)


def make_base_aic(path: Path) -> Path:
    """Тестовая база клона: 5 записей (3 не-донжона + 2 донжона), N=5."""
    entries = [
        AicBuildEntry(w0(100, 10, 10), w1(10, 5)),   # не-донжон (kind UNKNOWN)
        AicBuildEntry(w0(101, 20, 11), w1(20, 6)),
        AicBuildEntry(w0(21, 30, 12), w1(1, 0)),     # малый донжон
        AicBuildEntry(w0(102, 40, 13), w1(30, 7)),
        AicBuildEntry(w0(22, 50, 14), w1(2, 0)),     # средний донжон (primary)
    ]
    base = AicFile(path=None, n=len(entries), entries=entries,
                   general_values=list(range(1000, 1050)), extra_value=77,
                   list_points=[0] * 240, group_points=[0] * 200,
                   list_flags=[0] * 240)
    path.write_bytes(base.roundtrip_bytes())
    return path


def valid_genome(**over) -> dict:
    """Валидный геном (контракт 03 §3.7) с переопределениями."""
    genome = {
        "first_attack_month": 14, "wave_count": 3, "wave_gap_months": 4,
        "wave_size_base": 20, "composition_melee_share": 0.55,
        "composition_ranged_share": 0.35, "siege_ram": 1, "siege_tower": 1,
        "siege_catapult": 2, "siege_ladders": 4, "breach_target": "gate",
        "feint_enabled": False, "feint_ratio": 0.2, "reserve_ratio": 0.2,
        "retreat_threshold": 0.35, "super_aggressive": False,
        "aic_key": "sieger", "economy_first": True,
        "defense_group_archers": 0.5, "recruit_priority_ranged": 5,
        "recruit_priority_melee": 5, "recruit_priority_siege": 3,
        "recruit_priority_defense": 4,
    }
    genome.update(over)
    return genome


# ---------------------------------------------------------------- архетипы
def test_archetypes_table():
    assert set(ARCHETYPES) == set(KEEP_KIND)
    for aid, prof in ARCHETYPES.items():
        assert isinstance(prof, dict)  # dict[str, dict] (бриф S5.2)
        assert {"name_ru", "keep_kind", "ranged_share", "melee_share",
                "first_attack_month", "wave_count", "wave_gap_months",
                "wave_size_base", "siege_mix"} <= set(prof)
        assert prof["keep_kind"] == KEEP_KIND[aid]
        assert prof["first_attack_month"] == FIRST_MONTH[aid]
        assert 6 <= prof["first_attack_month"] <= 30
        assert 0.3 <= prof["melee_share"] <= 0.8
        assert 0.15 <= prof["ranged_share"] <= 0.5


@pytest.mark.parametrize("aid", sorted(KEEP_KIND))
def test_synthetic_mode_valid_and_honest(aid):
    data = build_archetype_aic(aid)
    model = AicFile.loads(data)                    # формат валиден
    assert len(data) == SIZE_BASE + 8 * model.n    # 2928+8N
    assert model.roundtrip_bytes() == data         # round-trip байт-в-байт
    assert model.n == 1
    keep = model.primary_keep
    assert keep is not None and keep.kind == KEEP_KIND[aid]
    assert (keep.x, keep.z, keep.rotation) == (48, 40, 0)  # пример Олафа
    assert model.general_values == [0xFFFFFFFF] * 50       # UNKNOWN-маркер
    assert model.list_points == [0] * 240
    assert model.group_points == [0] * 200
    assert model.list_flags == [0] * 240
    res = build_archetype_aic_result(aid)          # честная пометка режима
    assert res["data"] == data
    assert res["mode"] == "synthetic_keep_only"
    assert res["warning"] == SYNTHETIC_WARNING
    assert "полный план замка" in res["warning"]


def test_unknown_archetype_rejected():
    for func in (build_archetype_aic, build_archetype_aic_result):
        with pytest.raises(DoctrineError):
            func("ninja")
    with pytest.raises(DoctrineError):
        invasion_plan("ninja")
    with pytest.raises(DoctrineError):
        build_doctrine("ninja")
    with pytest.raises(DoctrineError):
        build_archetype_aic("sieger", base_path=Path("нет_такого.aic"))


def test_clone_mode_sieger(tmp_path):
    base_path = make_base_aic(tmp_path / "base.aic")
    base = AicFile.load(base_path)
    data = build_archetype_aic("sieger", base_path)
    model = AicFile.loads(data)
    assert model.roundtrip_bytes() == data         # формат валиден
    assert model.n == 7                            # 5 записей + duplicate_tail 2
    keeps = [e for e in model.entries if e.is_keep]
    assert [(e.word0, e.word1) for e in keeps] == \
        [(e.word0, e.word1) for e in base.keep_entries]  # донжоны не тронуты
    assert model.primary_keep.kind == 22
    nonkeep = [e for e in model.entries if not e.is_keep]
    assert sorted(e.group for e in nonkeep) == [13, 23, 23, 33, 33]  # +3
    assert sorted(e.param for e in nonkeep) == [7, 8, 8, 9, 9]       # +2
    assert {e.group for e in nonkeep} != {10, 20, 30}  # group изменены
    # general values / extra / точки / флагы перенесены без изменений
    assert model.general_values == base.general_values
    assert model.extra_value == base.extra_value
    assert model.list_points == base.list_points
    assert model.group_points == base.group_points
    assert model.list_flags == base.list_flags
    assert build_archetype_aic_result("sieger", base_path)["mode"] == "clone"


def test_clone_mode_raider_light_castle(tmp_path):
    base_path = make_base_aic(tmp_path / "base.aic")
    model = AicFile.loads(build_archetype_aic("raider", base_path))
    assert model.n == 3                            # remove_tail 2 (лёгкий)
    assert [e.kind for e in model.entries] == [100, 21, 22]
    assert model.entries[0].group == 11            # group_shift +1
    assert model.primary_keep.kind == 22


def test_load_base_aic(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert load_base_aic(empty) is None
    assert load_base_aic(tmp_path / "нет_такого") is None
    base_path = make_base_aic(tmp_path / "base.aic")
    assert load_base_aic(tmp_path) == base_path     # первый *.aic каталога
    (tmp_path / "00_broken.aic").write_bytes(b"\x05\x00\x00\x00" + b"\x00" * 8)
    with pytest.warns(UserWarning, match="00_broken.aic"):
        assert load_base_aic(tmp_path) == base_path  # битые пропускаются
    only_bad = tmp_path / "only_bad"
    only_bad.mkdir()
    (only_bad / "broken.aic").write_bytes(b"\x02\x00\x00\x00" + b"\x00" * 4)
    with pytest.warns(UserWarning):
        assert load_base_aic(only_bad) is None


def test_write_archetypes_synthetic(tmp_path):
    result = write_archetypes(tmp_path / "out")
    assert set(result) == set(ARCHETYPES)
    for aid, info in result.items():
        assert set(info) == {"path", "mode"}        # {archetype: {"path","mode"}}
        assert info["mode"] == "synthetic_keep_only"
        path = info["path"]
        assert path.name == f"aic_{aid}_v1.aic"
        model = AicFile.load(path)
        assert model.roundtrip_bytes() == path.read_bytes()
        assert model.n == 1 and model.primary_keep.kind == KEEP_KIND[aid]


def test_write_archetypes_clone(tmp_path):
    base = AicFile.load(make_base_aic(tmp_path / "base.aic"))
    result = write_archetypes(tmp_path / "out", base_dir=tmp_path)
    assert {info["mode"] for info in result.values()} == {"clone"}
    for aid, info in result.items():
        model = AicFile.load(info["path"])
        assert model.roundtrip_bytes() == info["path"].read_bytes()
        assert model.general_values == base.general_values  # values не тронуты
    sieger = AicFile.load(result["sieger"]["path"])
    assert sieger.n == 7 and sieger.primary_keep.kind == 22
    # base_dir без .aic → честный синтез
    empty = tmp_path / "no_aic"
    empty.mkdir()
    result2 = write_archetypes(tmp_path / "out2", base_dir=empty)
    assert {info["mode"] for info in result2.values()} == \
        {"synthetic_keep_only"}


# --------------------------------------------------------------- хореографии
def test_invasion_plan_raider_default():
    plan = invasion_plan("raider")
    assert len(plan) == 2                    # без генома — только волны
    assert all(set(w) == WAVE_KEYS for w in plan)
    assert [w["after_months"] for w in plan] == [8, 11]  # first 8, gap 3
    assert plan[0]["after_months"] <= 12     # ранний тайминг (6–12 мес)
    for w in plan:
        assert w["from_marker"] == 1 and w["attack_marker"] == 2
        assert w["repeat"] is False
        assert all(isinstance(v, int) and v >= 1 for v in w["troops"].values())
        assert set(w["troops"]) <= set(MELEE_POOL) | set(RANGED_POOL)
        assert sum(w["troops"].values()) == 15   # wave_size_base профиля
    assert "catapult" not in plan[0]["troops"]   # осада — только осадник


def test_invasion_plan_follows_genome():
    genome = valid_genome(first_attack_month=10, wave_count=4,
                          wave_gap_months=3, wave_size_base=20,
                          composition_melee_share=0.6,
                          composition_ranged_share=0.3, siege_catapult=0)
    plan = invasion_plan("balanced", genome)
    waves = [e for e in plan if "troops" in e]
    assert len(waves) == 4
    assert [w["after_months"] for w in waves] == [10, 13, 16, 19]
    for w in waves:
        assert isinstance(w["after_months"], int)
        assert sum(w["troops"].values()) == 20       # wave_size_base
        melee = sum(v for u, v in w["troops"].items() if u in MELEE_POOL)
        ranged = sum(v for u, v in w["troops"].items() if u in RANGED_POOL)
        assert (melee, ranged) == (13, 7)  # 0.6/0.9 → 13, остаток 7
        assert all(isinstance(v, int) and v >= 1
                   for v in w["troops"].values())
    # retreat_threshold → отдельный элемент немедленной формы DSL
    assert {"action": "AITroopRetreat",
            "params": {"threshold": 0.35}} in plan
    assert all("after_months" not in e for e in plan if "action" in e)


def test_invasion_plan_sieger_catapult_in_troops():
    plan = invasion_plan("sieger")
    waves = [e for e in plan if "troops" in e]
    assert [w["after_months"] for w in waves] == [18, 22, 26]
    assert waves[0]["troops"]["catapult"] == 2   # siege_mix профиля (1–2)
    assert sum(waves[0]["troops"].values()) == 26 + 2
    assert all("catapult" not in w["troops"] for w in waves[1:])
    boost = invasion_plan("sieger", valid_genome(siege_catapult=3))
    assert [e for e in boost if "troops" in e][0]["troops"]["catapult"] == 3
    off = invasion_plan("sieger", valid_genome(siege_catapult=0))
    assert all("catapult" not in e["troops"] for e in off if "troops" in e)


def test_invasion_plan_feint():
    genome = valid_genome(feint_enabled=True, first_attack_month=20)
    plan = invasion_plan("sieger", genome)
    waves = [e for e in plan if "troops" in e]
    assert len(waves) == 4                    # 3 волны + отвлекающая
    feint, first_main = waves[0], waves[1]
    assert feint["after_months"] == 20 - 2    # на 2 мес раньше первой
    assert first_main["after_months"] == 20
    assert sum(feint["troops"].values()) == round(20 * 0.2)  # ratio доли
    assert sum(feint["troops"].values()) < sum(first_main["troops"].values())
    assert all(set(w) == WAVE_KEYS for w in waves)
    assert all(v >= 1 for w in waves for v in w["troops"].values())


def test_invasion_plan_specials_and_determinism():
    genome = valid_genome(super_aggressive=True)
    plan = invasion_plan("sieger", genome)
    specials = [e for e in plan if "action" in e]
    assert {"action": "AITroopRetreat", "params": {"threshold": 0.35}} \
        in specials
    assert {"action": "SuperAggressiveTroops",
            "params": {"enabled": True}} in specials
    program = compile_events(specials)       # немедленная форма DSL (05 §5.4)
    assert {a["action"] for r in program.records for a in r["actions"]} == \
        {"AITroopRetreat", "SuperAggressiveTroops"}
    # детерминизм: один сид → один план; без rng — тоже стабильно
    assert invasion_plan("archer", rng=random.Random(42)) == \
        invasion_plan("archer", rng=random.Random(42))
    assert invasion_plan("raider") == invasion_plan("raider")
    g = valid_genome(feint_enabled=True, super_aggressive=True)
    assert invasion_plan("sieger", g, random.Random(1)) == \
        invasion_plan("sieger", g, random.Random(1))
    assert invasion_plan("sieger", g) == invasion_plan("sieger", g)


# ------------------------------------------------------- контракт doctrine.yaml
GOLDEN_DOCTRINE_YAML = """\
doctrine_id: doc_sieger_v2
version: 2
archetype: sieger
aic_file: templates/doctrines/aic_sieger_v2.aic
gamerules_patch: null
invasion_choreography: []
genome:
  first_attack_month: 14
  wave_count: 3
  wave_gap_months: 4
  wave_size_base: 20
  composition_melee_share: 0.55
  composition_ranged_share: 0.35
  siege_ram: 1
  siege_tower: 1
  siege_catapult: 2
  siege_ladders: 4
  breach_target: gate
  feint_enabled: false
  feint_ratio: 0.2
  reserve_ratio: 0.2
  retreat_threshold: 0.35
  super_aggressive: false
  aic_key: sieger
  economy_first: true
  defense_group_archers: 0.5
  recruit_priority_ranged: 5
  recruit_priority_melee: 5
  recruit_priority_siege: 3
  recruit_priority_defense: 4
provenance:
  origin: manual
  generation: 0
  parents: []
  evaluated_matches: 0
  winrate: 0.0
  honesty_violations: 0
"""


def test_doctrine_yaml_roundtrip(tmp_path):
    src = tmp_path / "doctrine.yaml"
    src.write_text(GOLDEN_DOCTRINE_YAML, encoding="utf-8")
    d1 = load_doctrine(src)
    assert d1["doctrine_id"] == "doc_sieger_v2"
    assert d1["version"] == 2
    assert d1["invasion_choreography"] == []
    assert d1["genome"]["siege_catapult"] == 2
    saved = save_doctrine(d1, tmp_path / "copy.yaml")
    assert load_doctrine(saved) == d1          # load → save → load без потерь
    with pytest.raises(DoctrineError):
        load_doctrine(tmp_path / "missing.yaml")


def test_genome_spec_covers_contract():
    assert len(GENOME_SPEC) == 23
    assert set(GENOME_SPEC) == set(valid_genome())


def test_build_doctrine():
    d = build_doctrine("sieger")
    assert validate_doctrine(d) == d           # канонична сразу
    assert d["doctrine_id"] == "doc_sieger_v1"
    assert d["genome"]["first_attack_month"] == 18   # из профиля
    assert d["genome"]["aic_key"] == "sieger"
    assert d["provenance"] == {"origin": "manual", "generation": 0,
                               "parents": [], "evaluated_matches": 0,
                               "winrate": 0.0, "honesty_violations": 0}
    # invasion_choreography заполняется из invasion_plan (S5.6)
    assert d["invasion_choreography"] == invasion_plan("sieger", d["genome"])
    d2 = build_doctrine("raider", valid_genome(first_attack_month=10))
    first_wave = next(e for e in d2["invasion_choreography"]
                      if "troops" in e)
    assert first_wave["after_months"] == 10    # параметры генома учтены


def test_build_doctrine_save_load_roundtrip(tmp_path):
    d = build_doctrine("balanced", valid_genome(feint_enabled=True))
    saved = save_doctrine(d, tmp_path / "doc.yaml")
    assert load_doctrine(saved) == d


RANGE_VIOLATIONS = [  # по одному нарушению на диапазон 08 §8.3
    ("first_attack_month", 5), ("first_attack_month", 31),
    ("wave_count", 0), ("wave_count", 6),
    ("wave_gap_months", 1), ("wave_gap_months", 11),
    ("wave_size_base", 7), ("wave_size_base", 41),
    ("composition_melee_share", 0.29), ("composition_melee_share", 0.81),
    ("composition_ranged_share", 0.14), ("composition_ranged_share", 0.51),
    ("siege_ram", 4), ("siege_tower", 3), ("siege_catapult", 5),
    ("siege_ladders", 9), ("breach_target", "gatehouse"),
    ("feint_ratio", 0.09), ("feint_ratio", 0.31),
    ("reserve_ratio", -0.1), ("reserve_ratio", 0.41),
    ("retreat_threshold", 0.19), ("retreat_threshold", 0.61),
    ("defense_group_archers", 0.19), ("defense_group_archers", 0.81),
    ("recruit_priority_ranged", -1), ("recruit_priority_melee", 11),
    ("recruit_priority_siege", "много"), ("recruit_priority_defense", True),
    ("aic_key", "ninja"), ("feint_enabled", "да"), ("economy_first", 1),
    ("wave_count", True),
]


@pytest.mark.parametrize("field,bad", RANGE_VIOLATIONS)
def test_genome_range_violations(field, bad):
    with pytest.raises(DoctrineError):
        validate_genome(valid_genome(**{field: bad}))


def test_genome_boundaries_ok():
    assert validate_genome(valid_genome(
        first_attack_month=6, wave_count=1, wave_gap_months=2,
        wave_size_base=8, composition_melee_share=0.3,
        composition_ranged_share=0.15, siege_ram=0, siege_tower=0,
        siege_catapult=0, siege_ladders=0, feint_ratio=0.1,
        reserve_ratio=0.0, retreat_threshold=0.2,
        defense_group_archers=0.2, recruit_priority_ranged=0))
    assert validate_genome(valid_genome(
        first_attack_month=30, wave_count=5, wave_gap_months=10,
        wave_size_base=40, composition_melee_share=0.8,
        composition_ranged_share=0.5, siege_ram=3, siege_tower=2,
        siege_catapult=4, siege_ladders=8, feint_ratio=0.3,
        reserve_ratio=0.4, retreat_threshold=0.6,
        defense_group_archers=0.8, recruit_priority_ranged=10))
    g = valid_genome()
    del g["retreat_threshold"]
    with pytest.raises(DoctrineError):
        validate_genome(g)                     # отсутствует ген
    with pytest.raises(DoctrineError):
        validate_genome(valid_genome(dark_share=0.5))  # неизвестный ген


def test_doctrine_structure_violations():
    def broken(**over):
        d = build_doctrine("sieger")
        d.update(over)
        return d

    with pytest.raises(DoctrineError):
        validate_doctrine(broken(extra_key=1))          # посторонний ключ
    with pytest.raises(DoctrineError):
        d = build_doctrine("sieger"); del d["genome"]
        validate_doctrine(d)                            # нет ключа
    with pytest.raises(DoctrineError):
        validate_doctrine(broken(archetype="ninja"))    # чужой архетип
    with pytest.raises(DoctrineError):
        validate_doctrine(broken(version=0))
    with pytest.raises(DoctrineError):
        d = broken(); d["provenance"]["origin"] = "cheater"
        validate_doctrine(d)
    for wave in ({"after_months": 0, "troops": {"swordsman": 5}},
                 {"after_months": 5, "troops": {}},
                 {"after_months": 5, "troops": {"Swordsman": 5}},
                 {"after_months": 5, "troops": {"swordsman": 0}},
                 {"after_months": 5, "troops": {"swordsman": 5},
                  "siege": {"catapult": 2}}):           # старый формат
        with pytest.raises(DoctrineError):
            validate_doctrine(broken(invasion_choreography=[wave]))
    with pytest.raises(DoctrineError):                  # неизвестное действие
        validate_doctrine(broken(invasion_choreography=[
            {"action": "Nuke", "params": {}}]))


def test_doctrine_for_persona():
    pool = ["hedgehog", "archer", "sieger", "raider", "balanced", "fortress"]

    def persona(aggr, builder, greed, arch_pool=None):
        pool_eff = pool if arch_pool is None else arch_pool
        return {"aggression": aggr, "builder": builder, "greed": greed,
                "loyal": 0.5, "doctrine_pool": pool_eff}

    aggressive = persona(0.9, 0.05, 0.05)
    assert doctrine_for_persona(aggressive, random.Random(7)) == "doc_raider_v1"
    assert doctrine_for_persona(aggressive, random.Random(7)) == "doc_raider_v1"
    built = doctrine_for_persona(persona(0.05, 0.9, 0.05), random.Random(3))
    assert built in ("doc_hedgehog_v1", "doc_fortress_v1")  # строители
    assert doctrine_for_persona(persona(0.05, 0.9, 0.05),
                                random.Random(3)) == built   # детерминизм
    assert doctrine_for_persona(persona(0.05, 0.05, 0.9),
                                random.Random(3)) == "doc_balanced_v1"
    # пул ограничивает выбор; ошибки — громкие
    assert doctrine_for_persona(persona(0.9, 0.0, 0.0,
                                        ["fortress", "raider"]),
                                random.Random(1)) == "doc_raider_v1"
    with pytest.raises(DoctrineError):
        doctrine_for_persona(persona(0.9, 0.0, 0.0, []), random.Random(1))
    with pytest.raises(DoctrineError):
        doctrine_for_persona({"aggression": 0.9}, random.Random(1))
    with pytest.raises(DoctrineError):
        doctrine_for_persona(persona(0.9, 0.0, 0.0, ["ninja"]),
                             random.Random(1))
    with pytest.raises(DoctrineError):
        doctrine_for_persona(aggressive, 42)      # rng не random.Random


def test_doctrine_scene_events():
    sides = [{"lord": "ai_lord", "role": "attacker"},
             {"lord": "player_lord", "role": "defender", "is_human": True}]
    doctrine = build_doctrine("sieger", valid_genome(feint_enabled=True,
                                                     super_aggressive=True))
    events = doctrine_scene_events(doctrine, sides, 40)
    program = compile_events(events)             # всё компилируется (05 §5.4)
    invasions = [r for r in program.records
                 if r["actions"][0]["action"] == "Invasion"]
    assert len(invasions) == 4                   # 3 волны + feint
    for r in invasions:
        params = r["actions"][0]["params"]
        assert params["owner"] == "ai_lord"      # атакующий лорд
        assert params["from_marker"] == 1 and params["attack_marker"] == 2
        assert params["repeat"] is False and params["troops"]
    actions = {a["action"] for r in program.records for a in r["actions"]}
    assert {"Invasion", "AITroopRetreat", "SuperAggressiveTroops",
            "Win", "Lose", "ControlLordsAI",
            "TimeUntilFinalInvasion"} <= actions
    # база scene_events("siege", ...) идёт раньше волн доктрины
    assert events[0]["action"] == "ControlLordsAI"
    # дефолтная доктрина: 3 волны + AITroopRetreat, без SuperAggressive
    plain = doctrine_scene_events(build_doctrine("sieger"), sides, 40)
    plain_actions = {e.get("action") for e in plain}
    assert "SuperAggressiveTroops" not in plain_actions
    assert "AITroopRetreat" in plain_actions
    # волны плана совместимы и с прямым каналом scene_events
    waves = [e for e in invasion_plan("sieger") if "troops" in e]
    alt = compile_events(scene_events("siege", sides, 40, invasion_plan=waves))
    assert sum(1 for r in alt.records
               if r["actions"][0]["action"] == "Invasion") == 3


# -------------------------------------------------------------------- aic_diff
def make_matrix_aic(path: Path, factor: int) -> Path:
    entries = [AicBuildEntry(w0(20, 48, 40), w1(1, 0))]
    model = AicFile(path=None, n=1, entries=entries,
                    general_values=[(factor * (j + 1)) % 97 for j in range(50)],
                    extra_value=0, list_points=[0] * 240,
                    group_points=[0] * 200, list_flags=[0] * 240)
    path.write_bytes(model.roundtrip_bytes())
    return path


def test_aic_diff_matrix_csv_cluster(tmp_path):
    for i, name in enumerate(("a.aic", "b.aic", "c.aic"), start=1):
        make_matrix_aic(tmp_path / name, i)
    (tmp_path / "broken.aic").write_bytes(b"\x05\x00\x00\x00" + b"\x00" * 8)
    with pytest.warns(UserWarning, match="broken.aic"):  # пометка о битом
        matrix = general_values_matrix(tmp_path)
    assert set(matrix) == {"a.aic", "b.aic", "c.aic"}
    assert all(len(v) == 50 for v in matrix.values())    # matrix 50 позиций
    assert matrix["b.aic"][0] == 2 and matrix["c.aic"][49] == 150 % 97
    csv = matrix_to_csv(matrix)
    lines = csv.strip().splitlines()
    assert lines[0] == "filename,position,value"         # длинный формат
    assert len(lines) == 1 + 3 * 50
    assert lines[1] == "a.aic,0,1" and lines[50] == "a.aic,49,50"
    assert lines[51] == "b.aic,0,2" and lines[150] == "c.aic,49,53"
    report = cluster_report(matrix)
    assert "Файлов: 3" in report
    assert "| позиция | n_unique | min | max | most_common |" in report
    assert "| 0 | 3 | 1 | 3 |" in report
    assert "| 49 |" in report                            # все 50 позиций
    assert sum(1 for ln in report.splitlines()
               if ln.startswith("| ") and ln[2].isdigit()) >= 50
    empty = cluster_report({})
    assert "Файлов: 0" in empty and "| 49 | 0 | — | — | — |" in empty
