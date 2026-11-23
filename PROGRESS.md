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
- Закрыто задач: 2/67; вечёр потрачено: ~(оценка не ведётся);
- Машинных часов GA: 0; round-trip корпуса: ещё не гонялся;
- Открытых вопросов: 0.

---

## Записи (новые сверху)

_(см. записи выше; append-only: новые записи вставлять сразу после этого заголовка)_

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

