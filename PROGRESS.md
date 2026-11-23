# PROGRESS.md — журнал проекта sh2tw (шаблон)

## 2026-11-23
### [служебно] Идентификация билда игры заказчика (готовит почву V5/S1.2) — 2026-11-23
- exe = сборка Steam v1.5.0: PE TimeDateStamp 0x5EA311C0 (2020-04-24) и размер 14 208 000 B совпадают с эталоном docs sh2-unofficial-patch (docs/bugs: «v1.5.0, ts 0x5ea311c0»).
- Отличия репака: version-ресурс переписан на 5.1.0.0 (string-таблица пуста), SteamLib.dll — Steam-эмулятор (сама игра не через Steam), папка v02.11.2022 = дата репака. На паттерн-поиск/идентичность exe патч опирается на PE-stamp+размер → предварительный вывод: трек 2 совместим (решает вечер V5).
- Факт записан в spec/sh2_tz/13_prilozheniya.md §J (G13). md5/crc32 exe — там же, для S1.2.
- Проверка: вывод python (PE-заголовок, GetFileVersionInfo) приложен в чате; артефакт замера — scratch, не в репо.

### [S0.1] Клон OpenSH2 Notes → ref/OpenSH2-Notes — done
План: клонировать github.com/nox7/OpenSH2 (depth 1) → скопировать Notes/ в ref/OpenSH2-Notes (read-only).
Реализовано: клон в scratch, Notes/ перенесён в ref/OpenSH2-Notes/.
acceptance_cmd `test -d ref/OpenSH2-Notes/FileFormats/S2M` → ACCEPT_OK.
Отклонение: клон делал агент (не человек) — содержательных отличий нет.


> Копировать в корень проекта `sh2tw/PROGRESS.md`. Запись — append-only, новые сверху.
> Агент ведёт после каждой задачи (протокол 00 §0.3). Человек читает и вписывает решения.

---

## Формат записи о задаче

```
## [S2.4] map_header.py: EstateMarkers, Scenario, Mission, EstateStartupTroopPlacement
- Дата: 2026-12-05
- План: (вставка плана из 3-8 пунктов, который писался до реализации)
- Сделано: (кратко, что реализовано)
- Проверки:
  $ pytest tests/test_map_header.py
  (вставить реальный вывод команд)
- Создано/изменено: tools/sh2tw/formats/map_header.py, tests/test_map_header.py
- Отклонения от плана: нет / … (причина)
- Открытые вопросы: нет / → QUESTIONS.md #N
- Коммит: [S2.4] …
```

## Служебные разделы (ведутся постоянно)

### Изменения ТЗ
_(дата, кто, файл, суть; только через человека)_

### Решения человека
_(дата, вопрос, решение — переносится из QUESTIONS.md после закрытия)_

### Блокировки
_(ID задачи, причина, что ждём)_

### Статистика (обновлять раз в этап)
- Закрыто задач: 9/67 (S0.1, S1.1-S1.3, S2.1-S2.3, S2.5, S2.9); частичные без человека: S2.0 (ценники ждут V7c), S2.4 (Scenario* raw, ждут V), S3.0 (каталог готов, выбор 8 — человек); вечёр потрачено: 0;
- Машинных часов GA: 0; round-trip корпуса: гоняется в pytest (159 файлов, побайтовая реконструкция);
- Открытых вопросов: 0.

---

## Записи (новые сверху)
### [S2.5] entities_decode+s2game: кадры размещённых объектов — done, 2026-11-23
- План: entities_decode.py+s2game.py (позы/классы/отпечатки юнитов и зданий в s2game) + tests/test_entities.py; приёмка pytest.
- Сделано (субагент, верифицировано родителем): строгие кадры Building-52 и Entity-59 с валидацией тела (защита от ложных 8-байтных совпадений); HeightLayer строгая разметка; классы-исключения raw с причинами (Statue, SpiralStairTeleport); rotation/owner/team сознательно UNKNOWN — доков нет, гадали бы — соврали бы.
- Проверки:
  $ PYTHONPATH=tools pytest tests/test_entities.py -q
  12 passed in 15.64s
  $ PYTHONPATH=tools pytest tests/ -q
  61 passed in 34.54s   (перепроверено родителем; reconstruct_segment==оригинал для всех 159 файлов после decode)
- Числа: 928 377 s2game-объектов корпуса; размещено 55 167 зданий + 266 770 актёров (222 класса).
- Создано: tools/sh2tw/formats/entities_decode.py, tools/sh2tw/formats/s2game.py, tests/test_entities.py; §J G20; registry S2.5 done.
- След. автономно: S2.6 snapshot_builder+CLI parse (делегировано сразу).
- Гейт человека: не требовался; V-уточнения owner/rotation позже.

### [S2.9 done + S3.0 механика] aic/gamerules + реестр карт (субагенты, верифицировано родителем) — 2026-11-23
- План: S2.9 aic.py+gamerules.py round-trip; S3.0 машинная часть реестра карт.
- Сделано: tools/sh2tw/formats/aic.py (.aic N@[0], записи 8B, секции по G19; 4 обрезанных test*.aic ожидаемо Sh2ParseError), gamerules.py (zlib с байта 0, lvl6 побайтовая переупаковка, распакованный сегмент через object_tree: GameRules+21 LordsRules raw/UNKNOWN), catalog_maps.py+CLI catalog-maps, ref/maps_catalog.csv (70 строк, 0 сбоев), §E.1 реестра карт; 19+4 новых тестов.
- Проверки:
  $ PYTHONPATH=tools pytest tests/ -q
  49 passed in 19.71s   (родитель перепроверил сам: zlib gameRules от байта 0; Olaf 2928+8*90=3648, kind20 x48 z40 — дословно docs)
  $ PYTHONPATH=tools python3 -m sh2tw.cli catalog-maps -> rows 70, failures []
- Исправлен прежний факт G4: «2111-байтный заголовок gameRules» НЕВЕРЕН — заголовка нет, zlib с байта 0 (G19).
- Открытые (не блокируют): семантика LordsRules и general-значений .aic — V-эксперименты; gamerules_fixed.dat (Lord Editor) на машине не найден — prefix-путь покрыт синтетикой.
- Гейт человека: выбор 8 заготовок из каталога; игровой вечер (V7c цены, Scenario/Mission доразбор, S2.10).

### [S2.0 частична + S2.4 частична] ref-CSV/валидатор и map_header.py — 2026-11-23
- S2.0: ref/unit_types.csv (22 строки, 8 полных цен из Прил. D) + ref/buildings.csv (64 класса корпуса) + CLI `validate-ref` (проходит: 0 ошибок). Закрытие ждёт замеров цен V7c (человек) — status pending c note.
- S2.4: tools/sh2tw/formats/map_header.py: MapHeader и EstateMarkers — полный семантический разбор + кросс-ccылки id на всех 70 картах; фикстуры chapter1/chapter8 совпали с docs OpenSH2 дословно (G17). Scenario/Mission/ScenarioEvent оставлены raw-passthrough: документ OpenSH2 расходится с payload'ами exe 2020-11-04 (G18), побайтовый round-trip при этом обеспечен S2.2/S2.3. Доразбор — за живым вечером (V).
- Проверки:
  $ PYTHONPATH=tools pytest tests/ -q
  26 passed in 19.43s
  $ PYTHONPATH=tools python3 -m sh2tw.cli validate-ref  -> RESULT: ref-контракт выполним
- Создано: tools/sh2tw/formats/map_header.py, tools/sh2tw/refvalidate.py, tests/test_map_header.py, ref/unit_types.csv, ref/buildings.csv, CLI-сабкоманда validate-ref; §J дополнен G17,G18.
- Следующее автономное (без человека): S2.9 aic.py+gamerules.py (round-trip, docs AIC.md + G4/G5 gamerules) — следующий агент может начать с него; контекст этой сессии исчерпан на подведении итогов.
- Гейт человека: игровой вечер V7c (цены юнитов) + V-замеры для Scenario/Mission/ScenarioEvent и S2.10.

### [S2.2 + S2.3] object_tree.py: обход по маркерам + round-trip корпуса — done, 2026-11-23
- План: generic-walk распакованных сегментов по Object.md; инвариант — побайтовая реконструкция; корпусная приёмка.
- Сделано: tools/sh2tw/formats/object_tree.py: magic-пара (5CA1AB1E,1) на старте каждого сегмента (G15); записи [id][reg] + [len][name] для новых reg; цепочка предков с правилом «письмо записи только для незарегистрированного предка» и lookahead-осторожностью; payload до маркера AF1EFFFF; Harvest подблоков [A5C1FFFF][reg][len][name] внутри payload (иначе поздние объекты с этим reg читаются как новые — крах на клановых картах); спец-граница HeightLayer по объявленным длинам (в плоскостях углов попадается ложный AF1EFFFF — обычный поиск drift'ит); единый класс Sh2ParseError.
- Проверки:
  $ PYTHONPATH=tools pytest tests/ -q
  23 passed in 18.17s   (включая test_corpus_walk_rebuild_all: 159 здоровых файлов, walk+recon побайтово; тесты corrupt-списка)
- Корпус: 70/70 карт + 89/95 сейвов (включая подпапку Saves/Restarts/, 17 файлов); 6 сейвов физически биты (byte rot маркеров, G16) — внесены в tests/corpus/corrupt_saves.txt, на них парсер падает громко (отдельный тест).
- Создано/изменено: tools/sh2tw/formats/object_tree.py (новый), tests/test_object_tree.py, tests/corpus/corrupt_saves.txt, §J реестра (G15,G16), task_registry (S2.2/S2.3 done).
- Отклонения от плана: нет; приёмка S2.3 «89+78» скорректирована фактом: реальный корпус = 70 карт + 95 сейвов (G12 устарел по составу сейвов — пересчёт при следующем каталоге).
- Открытые вопросы: нет.
- Коммит: [S2.2+S2.3] object tree walk, harvest inline regs, HeightLayer sizing, corpus round-trip.


### [S2.1] s2m_file.py контейнер .s2m/.sh2 — done, 2026-11-23
- Создано: tools/sh2tw/formats/s2m_file.py (FileHeaderModel, Segment с подбором zlib-уровня, S2mFile load/loads/roundtrip_bytes/roundtrip_ok/as_dict, Sh2ParseError); фикстуры tests/data/{sample.s2m,sample_notrail.s2m,sample_save.sh2}.
- Acceptance `pytest tests/test_s2m_file.py`: **12 passed** (5.06 s), включая test_corpus_roundtrip_all: ВСЕ файлы живого корпуса (91 карта + 96 сейвов) → roundtrip_bytes()==исходник, 0 падений; уровень сжатия находится перебором 0–9 (FLEVEL-подсказка из FLG).
- Баги-на-пути: (а) проверка CMF «(b[o]>>4)==8» (FLEVEL вместо CM) → (CMF&0x0F)==8+%31; (б) усечение хвоста потока проходило молча → контроль d.eof; (в) тест усечения на файле с tail=0 (у sample трейлер 52 B делал cut=10 легальным — G14); (г) опечатка латинского пути создала мусор C:\Users\Konstantin\ — файл переписан верно, удаление мусора → QUESTIONS #2 (агенту запрещено политикой).
- Открытых вопросов по форматной части нет. Коммит: [S2.1] …

### [S1.3] watcher Saves/ + лог файл-событий — done, 2026-11-23
- Создано: `tools/sh2tw/watcher.py` (snapshot/diff чистые + watch() поллинг, JSONL-логгер), `tests/test_watcher.py`, CLI-подкоманда `watch-saves` (--secs/--interval/--out), `pyproject.toml` (pytest pythonpath=["tools"] — точная acc-команда работает без env; pyright extraPaths).
- Acceptance: `pytest tests/test_watcher.py` → 4 passed. Смоук по живому каталогу: `watch-saves --secs 2 --interval 1` → 0 событий, exit 0 (писать было некому — корректно).
- Баг-на-пути: локальный `from pathlib import Path` внутри одной ветки main() сделал `Path` локальной для всей функции → UnboundLocalError в watch-saves; убран (импорт на уровне модуля).
- Назначение: V3a (кадентность автосейвов, 10_эксперименты) + K3-раннер (02 §57). События: created/modified/deleted с t/size — это «лог действий» на файловом уровне; семантический разбор действий — парсер сейвов (S2.x, next).
- Отклонений от плана нет. Открытых вопросов нет. Коммит: ниже.

### [S1.2] check-build: exe == v1.5.0, отчёт V5.json — done, 2026-11-23
- Создано: `ref/build_fingerprint.json` (эталон G13: size/PE ts/md5/crc32), `tools/sh2tw/check_build.py`, подкоманда CLI `check-build`.
- Acceptance (реальный вывод): `PYTHONPATH=tools .venv/Scripts/python.exe -m sh2tw.cli check-build --report experiments/reports/V5.json` → все 4 checks match=true, RESULT «совпадает с v1.5.0», exit 0; `experiments/reports/V5.json` создан (решение track2 — UNKNOWN, ждёт вечер V5 по 10_эксперименты).
- Баг-на-пути (зафиксирован): первый вариант читал COFF TimeDateStamp по смещению pe_off+4+20 (неверно, получились 0xa010b); верно pe_off+8. Пойман сверкой с md5/crc-эталоном — эталонные хеши работают как канареечный тест; в V5.json это событие не отражено, т.к. финальный прогон чистый.
- Отклонений от плана нет. Открытых вопросов нет.
- Коммит: ниже.

### [S1.1] tools/sh2tw: cli + backup (Maps+Saves) — done, 2026-11-23
- Создано: `tools/sh2tw/{__init__,paths,backup,cli}.py`; конфиг `config/project.ini` (S0.0, ключ maps_dir_game/maps_dir_user расширен в paths.py).
- Acceptance (реальный вывод):
  ```
  $ PYTHONPATH=tools .venv/Scripts/python.exe -m sh2tw.cli backup --dry-run
  {stamp:…, targets: maps_game: 91 файлов/38 845 182 B; maps_user: 0; saves: 96/123 352 633 B} exit 0
  ```
  Реальный прогон (тот же день, полный бэкап по 00 §63): `backup/maps_game_2026-11-23_113430` — 91 файл, `backup/saves_2026-11-23_113430` — 96 файлов (пересчёт find-ом совпал с манифестом). `maps_user` (Documents/Stronghold 2/Maps) не существует — юзер-карт пока нет, цель пустая.
  Примечание: запуск требует PYTHONPATH=tools и venv (`uv venv .venv --python 3.12`; pytest 9.2, pyyaml) — чистый `python` хостовой среды без pytest/pip.
- Отклонения: вместо отдельного `tools/backup_maps.py` — модуль пакета `sh2tw.backup` + CLI-подкоманда (реестр требует ровно acc-команду `python -m sh2tw.cli backup`, т.е. пакетная форма и есть соответствие реестру; имя файла из 00 §63 — устаревшая форма).
- Открытые вопросы: → QUESTIONS.md #1 (нумерация задач этапа S1 в 09 расходится с реестром; каталожный источник — реестр).
- Коммит: [S1.1] …

### Служебная: venv проекта
- `.venv` (uv, Python 3.12.14, pytest 9.2.0, pyyaml) — стандартный интерпретатор задач; `.gitignore` добавлен (.venv/, backup/).

