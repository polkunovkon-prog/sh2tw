"""Тесты контракта полной кампании «Войны Вольмарских марок» (S8.1–S8.3).

Полный прогон валидации campaigns/main/campaign_config.json через
campaigns_data.load_campaign_config (validate_config + normalize_config),
сводка describe_campaign, связность графа регионов и мини-смоук сезонного
цикла (new_game + 2 × next_season) с проверкой детерминизма.
"""
from __future__ import annotations

import json
from pathlib import Path

from sh2tw import campaigns_data
from sh2tw.shell import season
from sh2tw.shell import state as st

REPO = Path(__file__).resolve().parents[1]
CAMPAIGN = REPO / "campaigns" / "main" / "campaign_config.json"


def _bfs(config: dict, start: str) -> set[str]:
    """Достижимые из start регионы по графу соседств (BFS)."""
    by_id = {r["id"]: r for r in config["regions"]}
    seen, queue = {start}, [start]
    while queue:
        for nb in by_id[queue.pop()].get("neighbors") or []:
            if nb not in seen:
                seen.add(nb)
                queue.append(nb)
    return seen


# ============================================================= контракт конфига
def test_full_campaign_config_validates():
    cfg = campaigns_data.load_campaign_config(CAMPAIGN)
    assert cfg["campaign_id"] == "main_v1"
    assert cfg["title"] == "Войны Вольмарских марок"
    st.validate_config(cfg)          # нормализованная копия тоже валидна
    assert cfg["pacing"]["seasons_per_year"] == 4
    assert cfg["events"]["probabilities"]["rebellion"] > 0   # анти-снежный ком


def test_load_campaign_config_raises_value_error(tmp_path: Path):
    bad = tmp_path / "campaign_config.json"
    bad.write_text('{"schema_version": "1.0"}', encoding="utf-8")
    try:
        campaigns_data.load_campaign_config(bad)
    except ValueError as e:
        assert "campaign_id" in str(e)
    else:
        raise AssertionError("ожидался ValueError на неполном конфиге")


def test_describe_campaign_summary():
    cfg = campaigns_data.load_campaign_config(CAMPAIGN)
    info = campaigns_data.describe_campaign(cfg)
    assert info["regions"] == 12
    assert info["lords"] == 5
    assert info["castles"] >= 5
    assert info["villages"] >= 6
    assert info["victory_short"] == {"type": "eliminate_lords",
                                     "lords": ["l_hawk", "l_olaf"],
                                     "by_season": 30}
    assert info["victory_full"] == {"type": "control_regions", "count": 9,
                                    "of": 12, "by_season": 60}


# ==================================================================== граф
def test_graph_bfs_covers_all_regions():
    cfg = campaigns_data.load_campaign_config(CAMPAIGN)
    assert len(cfg["regions"]) == 12
    assert _bfs(cfg, cfg["regions"][0]["id"]) == {r["id"] for r in
                                                  cfg["regions"]}
    by_id = {r["id"]: r for r in cfg["regions"]}
    for region in cfg["regions"]:    # симметрия соседств (как validate_config)
        for nb in region.get("neighbors") or []:
            assert region["id"] in (by_id[nb].get("neighbors") or [])


def test_ai_lords_start_in_castle_regions():
    cfg = campaigns_data.load_campaign_config(CAMPAIGN)
    by_id = {r["id"]: r for r in cfg["regions"]}
    ai = [l for l in cfg["lords"] if not l.get("is_human")]
    assert len(ai) == 4
    starts = set()
    for lord in ai:
        region = by_id[lord["start_region"]]
        assert region["type"] == "castle"
        assert region["map_template"]
        starts.add(lord["start_region"])
    assert len(starts) == 4          # старты ИИ не совпадают, «врозь»


# ========================================================== сезонный смоук
def _two_seasons() -> dict:
    cfg = campaigns_data.load_campaign_config(CAMPAIGN)
    s = st.new_game(cfg, rng_seed=42)
    r1 = season.next_season(s, cfg)
    r2 = season.next_season(s, cfg)
    assert r1["season"] == 1 and r2["season"] == 2
    return s


def test_seasonal_smoke_two_seasons():
    s = _two_seasons()
    assert s["phase"] == "PLAYER_ACTIONS"
    assert s["season"] == 2 and s["season_name"] == "Лето"
    assert s["treasury"]["gold"] != 500          # доходы начислены
    assert len(s["ai_treasury"]) == 4            # казны всех ИИ живут
    assert len(s["regions"]) == 12               # ни один регион не потерян
    assert not (REPO / "campaigns" / "main" / "campaign_state.json").exists()


def test_determinism_same_seed_identical_state():
    first = _two_seasons()
    second = _two_seasons()
    dump = json.dumps(first, sort_keys=True, ensure_ascii=False)
    assert dump == json.dumps(second, sort_keys=True, ensure_ascii=False)
