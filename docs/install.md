# Установка sh2tw и запуск кампании

Пошаговая инструкция для Windows. Руководство по игре — [docs/player_guide.md](player_guide.md).

## 1. Требования

- **Windows 10/11** (оболочка и генератор запускаются на любом Python, но живые
  бои идут в Windows-игре).
- **Stronghold 2** — Steam-версия v1.5.0 или совместимый репак (сверка билда —
  команда `check-build`, раздел 4). Нужна **легальная копия** игры: файлы игры в
  репозиторий не входят и не распространяются.
- **Python 3.11+** — при установке отметьте галочку **Add python.exe to PATH**.

## 2. Установка проекта

```powershell
git clone <адрес-репозитория> sh2tw   # или распакуйте архив
cd sh2tw
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install pytest pyyaml fastapi uvicorn httpx
```

Проверка (все тесты зелёные; `pythonpath` подтягивается из `pyproject.toml`):

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 3. Настройка config/project.ini

Откройте `config/project.ini` и укажите пути к вашей игре (пример заполнения уже
есть в файле):

```ini
[paths]
game_dir     = D:\Games\Stronghold 2\Stronghold 2 Steam Edition   ; каталог с Stronghold2.exe
maps_dir_game= D:\Games\Stronghold 2\...\Maps                     ; каталог карт игры
maps_dir_user= C:\Users\<Вы>\Documents\Stronghold 2\Maps          ; пользовательские карты
saves_dir    = C:\Users\<вы>\Documents\Stronghold 2\Saves         ; сейвы (для детекта исхода)
```

Ключевые поля: `game_dir` — каталог с `Stronghold2.exe`; `maps_dir_game` —
каталог `Maps/` игры; `saves_dir` — `Documents/Stronghold 2/Saves`;
`maps_dir_user` — ваши пользовательские карты.

## 4. Первый запуск: бэкап, билд, каталог карт

Команды CLI выполняются с `PYTHONPATH=tools` (модули лежат в `tools/`):

```powershell
$env:PYTHONPATH = "tools"
$env:PYTHONIOENCODING = "utf-8"    # кириллица в консоли PowerShell

.\.venv\Scripts\python.exe -m sh2tw.cli backup        # бэкап Maps/ и Saves/ (S1.1)
.\.venv\Scripts\python.exe -m sh2tw.cli check-build   # сверка exe с эталоном Steam v1.5.0 (S1.2)
.\.venv\Scripts\python.exe -m sh2tw.cli catalog-maps  # реестр карт-заготовок → ref/maps_catalog.csv (S3.0)
```

- `backup` — обязательно перед первым живым боем (генератор кладёт карты
  `S2TW_*` в игровой каталог Maps/).
- `check-build` — «ок/отличается от эталона»: репаки с переписанными ресурсами
  работают, но сообщите о расхождении.
- `catalog-maps` — машиночитаемый каталог карт (нужен для отбора шаблонов,
  раздел 6).

## 5. Запуск кампании

```powershell
$env:PYTHONPATH = "tools"
.\.venv\Scripts\python.exe -m sh2tw.shell.api --campaign campaigns/main --port 8402
```

Откройте браузер: **http://127.0.0.1:8402**. Если `campaigns/main/campaign_state.json`
не существует — оболочка создаст новую партию автоматически. Дальше — «Быстрый
старт» в [docs/player_guide.md](player_guide.md). Интерактивная документация
REST API — http://127.0.0.1:8402/docs.

## 6. Подключение живых боёв (опционально)

Без этого шага все бои решаются авто-резолвом — кампания полностью играбельна.

1. Отберите **6–10 карт-заготовок** из своего каталога игры (кандидаты — в
   `ref/maps_catalog.csv`; план: 2 полевые, 3 штурмовые, 2–3 театральные,
   1–2 специальные) и скопируйте их в `templates/maps/`.
2. В редакторе карт игры расставьте **маркеры вторжений** на заготовках
   (регламент S3.1): точки входа атакующих, цель обороны, эстейт-деревни ИИ.
3. Заполните реестр `templates/templates.json` (формат —
   `tools/sh2tw/scenes/templates.py`, `load_registry`):

   ```json
   {"schema_version": "1.0", "templates": [
     {"template_id": "tpl_field_01",
      "source": {"kind": "repo", "file": "Two Pronged Crown.s2m"},
      "sha256": "<хэш из catalog-maps>",
      "roles": ["field"]},
     {"template_id": "tpl_wolfs_lair_01",
      "source": {"kind": "repo", "file": "Whitebear.s2m"},
      "sha256": null,
      "roles": ["siege", "specialty"]}
   ]}
   ```

   Роли: `field` (полевой бой), `siege` (штурм), `defense` (оборона),
   `theater` (сцена развития), `specialty`. Если реестр пуст — оболочка берёт
   дефолтную рекомендацию из каталога, иначе — fallback на авто-резолв.

## 7. Доктрины ИИ (опционально)

Лорды кампании ссылаются на профили `aic_hawk`, `aic_bull`, `aic_olaf`,
`aic_king` и доктрины `doc_*_v1`. Сгенерируйте архетипы из `.aic` своей игры
(режим «клона» — ванильный план замка + правки архетипа; без `base_dir` будет
синтетический донжон с UNKNOWN-секциями — честно помечается предупреждением):

```powershell
$env:PYTHONPATH = "tools"
.\.venv\Scripts\python.exe -c "from pathlib import Path; from sh2tw.doctrines.archetypes import write_archetypes; write_archetypes(Path('doctrines'), base_dir=Path(r'D:\Games\Stronghold 2\...\aic'))"
```

Готовые файлы `aic_<архетип>_v1.aic` положите в каталог, на который ссылается
конфиг кампании (или оставьте дефолты — ИИ работает и на встроенных доктринах).

## 8. Удаление / откат к ванили

```powershell
python tools/restore_vanilla.py    # удалит сгенерированные карты S2TW_* из Maps/
```

Затем можно просто удалить каталог проекта; файлы игры не изменялись (бэкап
раздела 4 — страховка). Полезно также: `python -m sh2tw.cli cleanup-maps` —
удаление только сгенерированных карт без удаления проекта.

## 9. Частые проблемы

- **Кириллица в путях / кракозябры в консоли**: `$env:PYTHONIOENCODING = "utf-8"`
  перед запуском команд; пробелы в путях — берите в кавычки.
- **Порт 8402 занят**: запустите на другом — `--port 8403`.
- **«Карты игры не найдены»**: проверьте `config/project.ini` — `maps_dir_game`
  должен указывать на каталог `Maps` внутри папки игры, `game_dir` — на каталог
  с `Stronghold2.exe`.
- **Тесты не видят модули**: запускайте pytest из корня репозитория
  (`pyproject.toml` задаёт `pythonpath = ["tools"]`); для ручного запуска
  Python — `$env:PYTHONPATH = "tools"`.
- **Живой бой не собирается** («нет шаблонов»): заполните
  `templates/templates.json` (раздел 6) — до тех пор бои идут авто-резолвом.
