"""Общие фикстуры тестов оболочки кампании (К1, ТЗ 07).

Мини-кампания из брифа: 3 региона (r01 castle игрока, r02 нейтральная
деревня, r07 castle ИИ l_hawk), победа eliminate_lords [l_hawk] к 30 сезону.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sh2tw.shell import state as st


def make_mini_config(**overrides) -> dict:
    """Конфиг мини-кампании (3 региона, 2 лорда) с полями образца 03 §3.1."""
    config = {
        "schema_version": "1.0",
        "campaign_id": "mini_v1",
        "title": "Мини-кампания для тестов",
        "regions": [
            {"id": "r01", "name": "Айронхилл", "type": "castle",
             "neighbors": ["r02", "r07"], "map_template": "tpl_castle_hills_01",
             "product": "iron", "base_income": 40,
             "castle_levels": {"1": "aic_wood_keep", "2": "aic_stone_keep",
                               "3": "aic_small_castle"},
             "garrison_cap": 60},
            {"id": "r02", "name": "Пшеничная нива", "type": "village",
             "neighbors": ["r01", "r07"], "product": "wheat",
             "base_income": 28, "purchase_cost_honour": 100},
            {"id": "r07", "name": "Перевал Трёх Башен", "type": "castle",
             "neighbors": ["r01", "r02"], "map_template": "tpl_castle_pass_01",
             "product": "stone", "base_income": 44,
             "castle_levels": {"1": "aic_wood_keep", "3": "aic_small_castle",
                               "5": "aic_fortress"},
             "garrison_cap": 80},
        ],
        "lords": [
            {"id": "player", "name": "Константин", "is_human": True,
             "start_region": "r01"},
            {"id": "l_hawk", "name": "Лорд Мёллер Ястреб", "is_human": False,
             "start_region": "r07", "aic_base": "aic_hawk",
             "lord_editor_key": "hawk",
             "persona": {"aggression": 0.8, "greed": 0.2, "builder": 0.2,
                         "loyal": 0.2, "doctrine_pool": ["doc_rusher_v1"],
                         "preferred_doctrine": "doc_rusher_v1"}},
        ],
        "victory": {
            "short": {"type": "eliminate_lords", "lords": ["l_hawk"],
                      "by_season": 30},
            "full": {"type": "control_regions", "count": 3, "of": 3,
                     "by_season": 60},
        },
        "pacing": {"seasons_per_year": 4, "max_transitions_total": 15,
                   "theater_cooldown_seasons": 3, "max_empty_seasons_streak": 2,
                   "field_scene_minutes": [20, 45], "theater_months": [24, 36]},
        "economy": {"village_tax_gold_per_month": 50,
                    "army_upkeep_gold_per_unit_month": 0.2,
                    "honour_festival_income": 8},
        "autoresolve": {"unit_value_source": "ref/unit_types.csv",
                        "wall_bonus_per_castle_level": 0.15, "logit_k": 3.0},
        "events": {"probabilities": {"harvest_failure": 0.08, "plague": 0.05,
                                     "rats": 0.07, "fair": 0.10,
                                     "mercenaries": 0.08, "harsh_winter": 0.06,
                                     "embassy": 0.07, "hunt": 0.09, "feast": 0.06,
                                     "rebellion": 0.0}},
    }
    config.update(overrides)
    return config


@pytest.fixture
def mini_config() -> dict:
    return make_mini_config()


@pytest.fixture
def mini_campaign(tmp_path: Path) -> Path:
    """Каталог кампании с записанным конфигом."""
    campaign_dir = tmp_path / "mini"
    campaign_dir.mkdir()
    (campaign_dir / st.CONFIG_NAME).write_text(
        json.dumps(make_mini_config(), ensure_ascii=False, indent=2),
        encoding="utf-8")
    return campaign_dir


def make_state(config: dict, rng_seed: int = 42) -> dict:
    """Состояние новой партии на нормализованном конфиге (копия)."""
    return st.new_game(st.normalize_config(copy.deepcopy(config)),
                       rng_seed=rng_seed)
