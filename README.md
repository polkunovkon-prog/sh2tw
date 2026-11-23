# sh2tw — Stronghold 2 × Total War

Стратегический режим (кампания) поверх **Stronghold 2** (Firefly Studios): старт на стратегической карте, развитие региона и бои — на настоящих тактических картах игры, без «шаблонной подстановки».

Репозиторий содержит техническое задание и реализацию ядра: парсер/писатель форматов игры (`.s2m`, `.sh2`, `.aic`, `gameRules.dat`), снапшоты и diff, оболочку кампании.

> Для игры нужна легально приобретённая Stronghold 2. Файлы игры в репозиторий не входят.

## Статус

- Этапы 0–2: конвейер разбора файлов с побайтовым round-trip на корпусе карт и сейвов.
- `pytest`: **85 passed**.
- Машиночитаемый реестр задач — `spec/sh2_tz/task_registry.json`, журнал — `PROGRESS.md`.

## Структура

| Путь | Содержимое |
|---|---|
| `spec/sh2_tz/` | Пакет ТЗ: архитектура, контракты данных, подсистемы, этапы 0–8, риски |
| `tools/sh2tw/` | Код: `formats/` (s2m, map_header, object_tree, entities_decode, aic, gamerules), `snapshot_builder`, `diff_engine`, `watcher`, `backup`, `cli` |
| `tests/` | pytest: 85 тестов, включая round-trip на корпусе |
| `experiments/` | Отчёты верификационных экспериментов V-серии |
| `ref/OpenSH2-Notes/` | Конспекты реверса форматов из [nox7/OpenSH2](https://github.com/nox7/OpenSH2) (Unlicense) — справочный материал, read-only |
| `config/`, `campaigns/`, `templates/`, `ga_runs/` | Конфигурация, кампании, шаблоны карт, прогоны GA |

## Быстрый старт

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install pytest pyyaml
.\.venv\Scripts\python.exe -m pytest -q

# CLI (модули лежат в tools/, поэтому нужен PYTHONPATH)
$env:PYTHONPATH = "tools"
$env:PYTHONIOENCODING = "utf-8"   # иначе справка на кириллице падает в консоли cp866
.\.venv\Scripts\python.exe -m sh2tw.cli --help
```

Тесты берут `pythonpath = ["tools"]` из `pyproject.toml` — для них `PYTHONPATH` не нужен.

## Документация

Начните с [`spec/sh2_tz/README.md`](spec/sh2_tz/README.md) — индекс пакета ТЗ. Кратко о цели и границах — [`spec/sh2_tz/01_obzor_i_principy.md`](spec/sh2_tz/01_obzor_i_principy.md).

## Благодарности

`ref/OpenSH2-Notes` — производная от [OpenSH2](https://github.com/nox7/OpenSH2) (Unlicense); исходный проект распространяется как public domain.
