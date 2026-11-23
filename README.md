# sh2tw — Stronghold 2 × Total War

Стратегический режим (кампания) поверх **Stronghold 2** (Firefly Studios): старт на стратегической карте, развитие региона и бои — на настоящих тактических картах игры, без «шаблонной подстановки».

Репозиторий содержит техническое задание и реализацию: парсер/писатель форматов игры (`.s2m`, `.sh2`, `.aic`, `gameRules.dat`), снапшоты и diff, генератор сцен, доктрины ИИ и GA, оболочку кампании (веб-UI + REST API).

> Для игры нужна легально приобретённая Stronghold 2. Файлы игры в репозиторий не входят.

## Статус

- Этапы 0–3, 5–8 (машинные части): парсер с побайтовым round-trip, генератор сцен
  (патчер L1 / писатель MapHeader L2 / rehost L3 за гейтом V4), раннер сцены,
  честность, доктрины ИИ, GA-конвейер, **оболочка кампании с полным веб-UI** и
  кампания «Войны Вольмарских марок» (12 регионов, 5 лордов, 2 уровня победы).
- `pytest`: **327 passed** (31 corpus-тест скипается без файлов игры заказчика).
- Живые проверки (эксперименты V1–V12, плейтесты) — чек-лист `docs/install.md`;
  до их закрытия система полностью играется авто-резолвом.
- Машиночитаемый реестр задач — `spec/sh2_tz/task_registry.json`, журнал — `PROGRESS.md`.

## Быстрый старт (Windows)

```powershell
# 1) установка (python 3.11+ в PATH; детали — docs/install.md)
powershell -ExecutionPolicy Bypass -File install.ps1 -GameDir "C:\Games\Stronghold 2"

# 2) кампания → браузер http://127.0.0.1:8402
$env:PYTHONPATH = "tools"
.\.venv\Scripts\python.exe -m sh2tw.cli campaign --campaign campaigns/main
```

Без карт-шаблонов бои решаются авто-резолвом; подключение живых боёв
(карты `S2TW_*` для Stronghold 2) — `docs/install.md` §6.

## Структура

| Путь | Содержимое |
|---|---|
| `spec/sh2_tz/` | Пакет ТЗ: архитектура, контракты данных, подсистемы, этапы 0–8, риски |
| `tools/sh2tw/` | Код: `formats/` (s2m, map_header, object_tree, entities, aic, gamerules), `honesty/`, `scenes/` (patcher, event_dsl, mapheader_writer, rehost, generator), `runner/`, `shell/` (сезонный цикл, ИИ, экономика, дипломатия, авто-резолв, FastAPI + веб-UI), `doctrines/`, `ga/` |
| `campaigns/main/` | Кампания «Войны Вольмарских марок» (campaign_config.json) |
| `tests/` | pytest: 327 тестов, включая round-trip на корпусе и integration API |
| `templates/` | Реестр шаблонов карт + доктрины (заполняется пользователем, S3.1) |
| `ref/` | Справочники: unit_types, buildings, maps_catalog, enums, OpenSH2-Notes |
| `ga_runs/` | Артефакты GA-прогонов (не в git) |
| `docs/` | `player_guide.md` (как играть), `install.md` (установка) |

## CLI

```
PYTHONPATH=tools python -m sh2tw.cli {backup|check-build|validate-ref|catalog-maps|
  parse|diff|diff-maps|build-scene|cleanup-maps|honesty|campaign|watch-saves}
```

`campaign` — запуск оболочки (localhost:8402); `build-scene` — сборка карты сцены
из scene_spec; `diff-maps` — разработка якорных патчей (05 §5.3); `honesty` —
протокол честности матча.

## Документация

- Игроку: [`docs/player_guide.md`](docs/player_guide.md)
- Установка: [`docs/install.md`](docs/install.md)
- ТЗ (индекс): [`spec/sh2_tz/README.md`](spec/sh2_tz/README.md)

## Благодарности

`ref/OpenSH2-Notes` — производная от [OpenSH2](https://github.com/nox7/OpenSH2) (Unlicense); исходный проект распространяется как public domain.
