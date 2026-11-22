# 03. Контракты данных

Общие правила: (1) все JSON — UTF-8, без BOM; (2) каждый файл верхнего уровня имеет `schema_version` (строка `"M.m"`); (3) неизвестные поля читатель игнорирует, но не удаляет при round-trip; (4) время — игровое в месяцах от начала сцены/кампании и реальное в минутах (поля `*_months`, `*_real_min`); (5) идентификаторы — `snake_case` ASCII; имена собственные (лорды, регионы) — человекочитаемые, кириллица допускается в `name`.

Роспись армии (тип × количество × ветеранство) везде представляется одинаково — объект «тип юнита → запись»:

```json
{
  "archer":   {"count": 24, "vet": 0.25},
  "spearman": {"count": 12, "vet": 0.0},
  "knight":   {"count": 4,  "vet": 0.5}
}
```

`vet` — средняя доля ветеранов типа (0–1); ветеран = выжил в ≥1 бою (оболочка ведёт сама: в SH2 юнит-опыта нет — факт проверен 23.11.2026).

---

## 3.1. `campaign_config.json` — статическая конфигурация кампании

Авторируется один раз (человек + агент), не меняется в процессе партии. Пример (сокращён до 3 регионов, полная кампания — 12–16):

```json
{
  "schema_version": "1.0",
  "campaign_id": "main_v1",
  "title": "Войны Вольмарских марок",
  "regions": [
    {
      "id": "r01", "name": "Айронхилл", "type": "castle",
      "neighbors": ["r02", "r07"],
      "map_template": "tpl_castle_hills_01",
      "product": "iron",
      "base_income": 40,
      "castle_levels": {
        "1": "aic_wood_keep", "2": "aic_stone_keep", "3": "aic_small_castle",
        "4": "aic_big_castle", "5": "aic_fortress"
      },
      "garrison_cap": 60
    },
    {
      "id": "r02", "name": "Пшеничная нива", "type": "village",
      "neighbors": ["r01", "r03"], "product": "wheat",
      "base_income": 28, "purchase_cost_honour": 100
    },
    {
      "id": "r07", "name": "Перевал Трёх Башен", "type": "castle",
      "neighbors": ["r01", "r08"], "product": "stone",
      "base_income": 44, "map_template": "tpl_castle_pass_01",
      "castle_levels": {"1": "aic_wood_keep", "3": "aic_small_castle", "5": "aic_fortress"},
      "garrison_cap": 80
    }
  ],
  "lords": [
    {"id": "player", "name": "Константин", "is_human": true, "start_region": "r01"},
    {
      "id": "l_hawk", "name": "Лорд Мёллер Ястреб", "is_human": false,
      "start_region": "r07", "aic_base": "aic_hawk", "lord_editor_key": "hawk",
      "persona": {"aggression": 0.7, "greed": 0.5, "builder": 0.3, "loyal": 0.2,
                  "doctrine_pool": ["doc_rusher_v1", "doc_raider_v1"], "preferred_doctrine": "doc_rusher_v1"}
    }
  ],
  "victory": {
    "short": {"type": "eliminate_lords", "lords": ["l_hawk", "l_wolf"], "by_season": 30},
    "full":  {"type": "control_regions", "count": 9, "of": 12, "by_season": 60}
  },
  "pacing": {
    "seasons_per_year": 4, "max_transitions_total": 15,
    "theater_cooldown_seasons": 3, "max_empty_seasons_streak": 2,
    "field_scene_minutes": [20, 45], "theater_months": [24, 36]
  },
  "economy": {
    "village_tax_gold_per_month": 50,
    "army_upkeep_gold_per_unit_month": 0.2,
    "honour_festival_income": 8
  },
  "autoresolve": {
    "unit_value_source": "ref/unit_types.csv",
    "wall_bonus_per_castle_level": 0.15,
    "logit_k": 3.0
  }
}
```

Правила валидации: граф регионов связен; у каждого замкового региона непуст `castle_levels` и `map_template`; `id` уникальны; у ИИ-лордов указан `persona` со всеми 4 чертами (0–1) и непустым `doctrine_pool`.

## 3.2. `campaign_state.json` — изменяемое состояние партии

Обновляется только оболочкой; перед каждым изменением — копия в `campaigns/main/history/state_<season>_<n>.json` (undo-цепочка).

```json
{
  "schema_version": "1.0",
  "campaign_id": "main_v1",
  "season": 14,
  "rng_seed": 975318642,
  "treasury": {"gold": 1840, "honour": 260, "rank": 6},
  "regions": {
    "r01": {"owner": "player", "castle_level": 2, "loyalty": 62,
            "development_points": 18, "garrison": {"archer": {"count": 18, "vet": 0.2}},
            "last_theater_snapshot": "snap_theater_s11.json"},
    "r07": {"owner": "l_hawk", "castle_level": 3, "loyalty": 40,
            "development_points": 31, "garrison": {"spearman": {"count": 22, "vet": 0.0}}}
  },
  "armies": {
    "army_01": {"owner": "player", "located_region": "r01", "lord_present": true,
                "roster": {"archer": {"count": 24, "vet": 0.25}, "spearman": {"count": 12, "vet": 0.0}}}
  },
  "diplomacy": {
    "pairs": {"player|l_hawk": "war", "player|l_ox": "peace", "l_hawk|l_wolf": "alliance"},
    "tributes": [{"from": "l_ox", "to": "player", "gold_per_season": 15, "until_season": 22}]
  },
  "counters": {
    "transitions_used": 7, "scenes_played": 8, "battles_auto": 12, "battles_manual": 6,
    "empty_seasons_streak": 0, "theater_last_season": 11
  },
  "events_log": ["S14: Урожай в Пшеничной ниве погиб (WheatDisease)"],
  "flags": {"coalition_against_leader_active": false}
}
```

## 3.3. `scene_spec.json` — заказ сцены (вход генератора)

```json
{
  "schema_version": "1.0",
  "scene_id": "sc_0042",
  "type": "siege",
  "created_by": "shell",
  "region": "r07",
  "duration_months": 40,
  "sides": [
    {"role": "attacker", "lord": "player", "is_human": true,
     "provision": {"channel": "estate_troops", "roster": {"archer": {"count": 24, "vet": 0.25},
                    "spearman": {"count": 12, "vet": 0.0}}},
     "budget_gold": 0, "budget_honour": 0},
    {"role": "defender", "lord": "l_hawk", "is_human": false,
     "provision": {"channel": "aic_template", "aic_key": "aic_small_castle",
                    "garrison_roster": {"spearman": {"count": 22, "vet": 0.0}}}}
  ],
  "map_source": {"kind": "template", "template_id": "tpl_castle_pass_01"},
  "map_header_overrides": {
    "estate_markers": "inherit",
    "scenario": {"lords_count": 2, "alliances": [["player"], ["l_hawk"]]},
    "mission_events": [
      {"after_months": 1, "action": "ControlLordsAI", "params": {"lords": ["l_hawk"], "enabled": true}},
      {"after_months": 2, "action": "Invasion", "params": {
          "owner": "player", "from_marker": 1, "attack_marker": 2,
          "troops": {"archer": 24, "spearman": 12}, "repeat": false}},
      {"trigger": {"type": "EnemyLordDead", "params": {"lord": "l_hawk"}},
       "actions": [{"action": "Win"}]},
      {"trigger": {"type": "LordDies", "params": {"lord": "player"}},
       "actions": [{"action": "Lose"}]}
    ]
  },
  "honesty": {"snapshot_points": ["start", "end"], "enabled": true},
  "notes": "Штурм перевала; гарнизон по snapshot региона r07"
}
```

`type` ∈ `field | siege | defense | development`. `map_source.kind` ∈ `template | rehost` (rehost = база из `.sh2`-снимка, см. 05 §5.5). Каналы провижининга: `estate_troops | invasion | war_chest | aic_template` (см. 02 §2.4; финальный выбор по V7). Внутренний DSL событий (`mission_events`) конвертируется генератором в записи ScenarioEvent (см. 05 §5.4, 13 Приложения A/B).

## 3.4. `scene_result.json` — итог сцены (выход парсера/раннера)

```json
{
  "schema_version": "1.0",
  "scene_id": "sc_0042",
  "outcome": "win",
  "outcome_channel": "autosave_parse",
  "duration_real_min": 34,
  "losses": {
    "attacker": {"archer": 6, "spearman": 4},
    "defender": {"spearman": 22}
  },
  "survivors": {
    "attacker": {"archer": {"count": 18, "vet": 0.25}, "spearman": {"count": 8, "vet": 0.0}}
  },
  "captures": ["r07"],
  "honour_delta": 40,
  "development_damage": {"r07": -1},
  "snapshot_end": "snap_sc0042_end.json",
  "honesty": {"pass": true, "report": "honesty_sc0042.json"},
  "anomalies": []
}
```

`outcome` ∈ `win | loss | draw | aborted`; `outcome_channel` ∈ `autosave_parse | ocr | manual | bridge`.

## 3.5. `snapshot.json` — снимок состояния мира из `.s2m/.sh2`

```json
{
  "schema_version": "1.0",
  "source": {"file": "S2TW_sc0042.s2m", "sha256": "…", "parsed_at": "2026-12-01T21:14:00"},
  "map": {"name": "S2TW_sc0042", "type": "warcampaign", "mapsize_class": 2},
  "game_time_months": 41,
  "lords": [
    {"index": 0, "name": "Константин", "alive": true, "gold": 420, "honour": 300,
     "rank": 6, "estates": [0, 1], "troops": {"archer": 18, "spearman": 8}},
    {"index": 1, "name": "Лорд Мёллер Ястреб", "alive": false, "gold": 0, "honour": 0,
     "rank": 0, "estates": [], "troops": {}}
  ],
  "buildings": [
    {"type_id": 34, "type_name": "Barracks", "x": 132, "z": 88, "owner_lord": 0, "hp_pct": 100}
  ],
  "estates": [
    {"marker_slot": 0, "type": "castle", "owner_lord": 0},
    {"marker_slot": 1, "type": "village", "owner_lord": 0, "product": "wheat"}
  ],
  "resources": {"gold_total_estimated": 420},
  "population": 64,
  "raw_unknown_objects": 12
}
```

Поля сырого слоя (`raw_unknown_objects` и связанные дампы `dump/`) обязательны: всё, что парсер не распознал, сохраняется в сыром виде и попадает в счётчик — метрика покрытия парсера (этап 2).

## 3.6. `events.json` / `events.jsonl` — лента различий двух snapshot'ов

`events.json` (результат `diff snapshot_a.json snapshot_b.json`):

```json
{
  "schema_version": "1.0",
  "from": "snap_sc0042_start.json", "to": "snap_sc0042_end.json",
  "delta_months": 41,
  "events": [
    {"t_months": 5,  "kind": "building_built", "lord": 0, "building": "Barracks", "x": 132, "z": 88},
    {"t_months": 12, "kind": "battle", "attacker_lord": 0, "defender_lord": 1, "losses": {"archer": 6}},
    {"t_months": 41, "kind": "lord_died", "lord": 1, "killer_lord": 0},
    {"t_months": 41, "kind": "estate_captured", "estate": 2, "from_lord": 1, "to_lord": 0}
  ]
}
```

`events.jsonl` (журнал кампании, append-only): одна строка = одно решение/итог оболочки: `{"ts": "…", "season": 14, "kind": "scene_applied", "scene_id": "sc_0042", "summary": "…"}`.

## 3.7. `doctrine.yaml` — доктрина ИИ

```yaml
doctrine_id: doc_sieger_v2
version: 2
archetype: sieger
aic_file: templates/doctrines/aic_sieger_v2.aic
gamerules_patch: gamerules_fair_sieger.json   # только честные поля, см. 08
invasion_choreography:
  - after_months: 14
    troops: {swordsman: 18, archer: 12}
    siege: {ram: 1, tower: 1, catapult: 2, ladders: 4}
    target: gate
  - after_months: 22
    troops: {swordsman: 12, crossbowman: 8}
    feint: {enabled: true, ratio: 0.2}
genome:
  first_attack_month: 14
  wave_count: 3
  wave_gap_months: 4
  composition_melee_share: 0.55
  reserve_ratio: 0.2
  retreat_threshold: 0.35
  siege_mix: {ram: 1, tower: 1, catapult: 2, ladders: 4}
  aic_priority_economy_first: true
provenance:
  origin: ga
  generation: 12
  parents: [doc_sieger_v1, doc_balanced_v3]
  evaluated_matches: 40
  winrate: 0.62
  honesty_violations: 0
```

Поля `genome` — параметры GA (полный список генов и диапазонов — 08 §8.3). Файл читается генератором сцен (подстановка в mission_events) и GA-движком.

## 3.8. `*.patch.json` — манифест якорных равнодлинных патчей

Один файл на шаблон карты. Патч никогда не адресуется абсолютным смещением — только якорем (уникальная цепочка байт) + смещением от конца якоря.

```json
{
  "schema_version": "1.0",
  "template_id": "tpl_castle_pass_01",
  "template_file": "templates/maps/Cross Pass.s2m",
  "template_sha256": "…",
  "patches": [
    {
      "id": "start_gold.lord0",
      "anchor_hex": "E8 03 00 00 00 00 00 00",
      "anchor_offset": 12,
      "expected_hex": "10 27 00 00",
      "new_hex": "C0 5D 00 00",
      "length_check": 4,
      "notes": "стартовое золото стороны 0 (Scenario), 10000 → 24000"
    }
  ]
}
```

Правила: `len(new_hex) == len(expected_hex)` (равнодлинность); якорь обязан встречаться в распакованном сегменте ровно 1 раз (иначе патч отклоняется); при несовпадении `expected_hex` патч отклоняется и падает с диффом — это защита от версии шаблона. Разработка патча: hexdiff эталона и правленой в редакторе копии (процедура — 05 §5.3).

## 3.9. `honesty_report.json` — протокол честности матча

```json
{
  "schema_version": "1.0",
  "scene_id": "sc_0042",
  "sides": [
    {"lord": "player", "t0": {"gold": 500, "troops_value": 800, "estates_income_month": 78},
     "t_end": {"gold": 120, "troops_value": 610}},
    {"lord": "l_hawk", "t0": {"gold": 500, "troops_value": 790, "estates_income_month": 75},
     "t_end": {"gold": 0, "troops_value": 0}}
  ],
  "accounting": {
    "l_hawk": {
      "income_expected_min": 0, "income_expected_max": 3120,
      "income_observed": 2980, "verdict": "ok"
    }
  },
  "verdict": "pass",
  "violations": []
}
```

Семантика (уточнение протокола из плана §7.3 — обоснование в файле 12): на старте сцены провижининг сторон **равен по стоимости ±10 %**; далее для каждой стороны считается бюджет дохода `income_expected_max = Σ(доход эстейтов) × месяцы × k_trade + стартовое золото` (k_trade = 1.3 — потолок торговли, калибруется); наблюдаемое суммарное потребление (прирост войск + построек + золота) сверх бюджета > 10 % = нарушение, матч бракуется. Сравниваются не абсолютные богатства (это наказывало бы ИИ за хорошую игру), а **баланс доходов и расходов**.

## 3.10. `ga_config.yaml` и артефакты GA

`ga_config.yaml` (ключевое): `population: 12`, `generations_max: 20`, `matches_per_candidate: 3`, `defenses_portfolio: [def_hedgehog, def_archers, def_killer_walls]`, `selection: {kind: tournament, k: 3}`, `elitism: 2`, `mutation: {sigma_rel: 0.15, gene_prob: 0.3}`, `crossover: uniform`, `speed: x3`, `instances: 2`, `stop: {winrate_plateau_generations: 5}`.

Артефакты на прогон (`ga_runs/<run_id>/`): `population_gen_<N>.json` (особи + фитнесы), `match_result.json` на матч (сценарий, обе стороны, исход, honesty), `champion.json` (лучшая особь + полный протокол валидации), `run_log.jsonl`.

## 3.11. Отчёт эксперимента `experiments/reports/V<N>.json`

Форма задаётся в файле 10 для каждого V; общий каркас: `{"v_id": "V4", "date": "…", "performer": "human", "hypothesis": "…", "result": "…", "metrics": {}, "decision": "…", "attachments": []}`.

## 3.12. `config/project.ini`

```ini
[paths]
game_dir = C:\Games\Stronghold 2
saves_dir = C:\Users\<user>\Documents\Stronghold 2\Saves
maps_dir = %(game_dir)s\Maps
backup_dir = <проект>\backup
[flags]
track2_enabled = false
game_speed_default = 1
[shell]
port = 8402
```

## 3.13. Сводный реестр файлов проекта

| Файл | Кто пишет | Кто читает | Этап |
|---|---|---|---|
| `campaign_config.json` | человек+агент (однократно) | оболочка, генератор | 7 |
| `campaign_state.json` + `history/` | оболочка | все подсистемы, человек | 7 |
| `scene_spec.json` | оболочка | генератор | 3 |
| `Maps/S2TW_<scene_id>.s2m` | генератор | игра (человек) | 3 |
| `snapshot.json` (`snap_*.json`) | парсер | оболочка, honesty, GA | 2 |
| `scene_result.json` | раннер+парсер | оболочка | 3 |
| `events.json` / `events.jsonl` | парсер / оболочка | человек, оболочка | 2/7 |
| `doctrine.yaml` | агент/GA | генератор, GA | 5–6 |
| `*.patch.json` | агент (по hexdiff) | патчер | 3 |
| `honesty_report.json` | парсер (honesty) | человек, GA | 2 |
| `ga_runs/**` | GA | человек | 6 |
| `experiments/reports/V*.json` | человек (с помощью агента) | все | 1 |
| `PROGRESS.md`, `QUESTIONS.md` | агент | человек, агент | 0+ |

Правило имён сгенерированных карт: `S2TW_<scene_id>_<type>.s2m` — префикс `S2TW_` отличает их от ванильных; очистка — `tools/cli.py cleanup-maps`.
