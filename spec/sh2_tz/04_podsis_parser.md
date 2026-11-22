# 04. Подсистема: парсер форматов (K4)

## 4.1. Назначение и границы

Парсер — фундамент всего проекта: из него выходят snapshot'ы (итоги сцен), протокол честности, диффы, и на нём же стоит round-trip валидация писателя карт. Входы: `.s2m` (карты), `.sh2` (сейвы; формат тот же — F1/F12), `.aic` (шаблоны замков), `gameRules.dat` (профили лордов). Выходы: `snapshot.json`, `events.json`, `honesty_report.json`, отчёты валидации.

Границы: парсер **не интерпретирует** семантику игры (что «хорошо»/«плохо») — только состояние. Непризнанные данные не выбрасываются: сохраняются сырыми (см. `raw_unknown_objects`).

Авторитетные доки формата (клонировать в `ref/OpenSH2-Notes/`, задача S0.1): `Notes/FileFormats/S2M/{Overview,FileHeader,Object}.md`, `S2M/MapHeaderSegment/{MapHeader,Scenario,Mission,ScenarioEvent,EstateMarkers,EstateStartupTroopPlacement}.md`, `S2M/S2GameSegment/HeightLayer.md`, `AIC.md`, `GR2/Overview.md`. При расхождении доков с реальными файлами игры прав файл игры + запись в реестр фактов (13, раздел J).

## 4.2. Модули

```
sh2tw/formats/
  s2m_file.py        # контейнер: заголовок, сегменты, zlib, round-trip
  object_tree.py     # обход дерева объектов по маркерам
  map_header.py      # MapHeader: Scenario, Mission, EstateMarkers, стартовые войска, ScenarioEvent
  s2game.py          # S2Game: raw + выборочные декодеры (HeightLayer)
  radar_map.py       # RadarMap: raw (прозрачный прокс)
  entities_decode.py # декодирование сущностей по ref/entities.csv
  aic.py             # .aic: разбор/сборка по формуле 2928+8N
  gamerules.py       # gameRules.dat: 2111 байт заголовка + zlib нод-дерево
  snapshot_builder.py# сведение в snapshot.json
  diff_engine.py     # snapshot A/B -> events.json
sh2tw/honesty/
  accounting.py      # расчёт бюджета доходов, verdict
```

Сигнатуры ключевых функций (обязательны к точному соблюдению):

```python
class S2mFile:
    @classmethod
    def load(cls, path: Path) -> "S2mFile": ...
    def roundtrip_bytes(self) -> bytes:
        """Пересборка файла из внутренней модели. Контракт: байт-в-байт равна исходнику."""
    @property
    def file_header(self) -> FileHeader: ...   # ASCII-таблицы опций
    @property
    def map_header(self) -> MapHeaderModel: ...
    @property
    def s2game_raw(self) -> bytes: ...

def parse_snapshot(path: Path, out: Path) -> Snapshot: ...
def diff_snapshots(a: Path, b: Path, out: Path) -> list[Event]: ...
def honesty_report(start: Snapshot, end: Snapshot, spec: SceneSpec) -> HonestyReport: ...
```

## 4.3. Алгоритмы

### Заголовок и сегменты (s2m_file.py)

1. Прочитать ASCII-заголовок: две таблицы опций — строки (`author`, `type` ∈ `kingmaker|warcampaign|peacecampaign|freebuild`) и целые (`mapsize`, `maxplayers`, `balanced`, `lastsave`, `version`). Точный синтаксис — [OpenSH2:FileHeader.md]; не гадать, сверять с реальными файлами.
2. Далее — последовательность zlib-сегментов. Обязательный порядок: MapHeader, RadarMap, S2Game (Overview.md, подтверждено 23.11.2026). Каждый сегмент: распаковать `zlib.decompress`; граница следующего — по полю длины в контейнере (см. FileHeader.md; при неоднозначности определить по парам реальных файлов и зафиксировать в реестре фактов).
3. Хранить: распакованные байты сегментов + уровень/стратегия сжатия исходника (для round-trip: перебор `zlib.compressobj(level)` 0–9 с побайтовым сравнением; уровень кэшируется в файл-сателлит `.meta.json` рядом с эталоном).

### Дерево объектов (object_tree.py)

Обход по маркерам (F2, подтверждено): `AF 1E FF FF` — конец объекта; `AD DE FF FF` — конец сегмента; `A5 C1 FF FF` — начало данных. Первый объект (MapHeader) — id и enum парсятся дважды (Overview.md). Каждый узел: `type_id`, сырые поля. Известные `type_id` декодируются по `ref/*.csv`; неизвестные — `RawObject(keep_bytes)` без изменений.

### MapHeader (map_header.py)

Декодирует: EstateMarkers (слоты по доке EstateMarkers.md — уточнить счёт слотов и размер записи по доке и hexdiff'ам), Scenario (лорды, стартовые ресурсы миссии, типы продукции деревень — до 16 лордов), Mission (доступность зданий и пр.), ScenarioEvent (триггер+действие записи — структура по ScenarioEvent.md), EstateStartupTroopPlacement (стартовые войска по эстейтам — по одноимённой доке). Модель MapHeader обязана поддерживать сериализацию обратно (её использует писатель — 05).

### S2Game (s2game.py)

Высоты: жёстко 256×256 float32 + 3 плоскости угловых высот (payload 3 407 932 байта — F3, байт-арифметика сходится). Никогда не пересобирать — только копировать. Объекты (постройки, растительность, юниты на карте) — через object_tree с реестром `ref/entities.csv`; счёт по типам попадает в snapshot.

### .aic (aic.py)

Формула длины `2928 + 8×N` (F4): N записей построек (kind, локальные X/Z, поворот; group, param) + 50 general values + 24 списка × 10 точек + 10 групп × 20 точек + 240 флагов; точки `Z*100+X`; донжоны 20–23. Полный разбор + сборка; diff двух `.aic` — инструмент дифф-протокола 50 значений (08 §8.6).

### gameRules.dat (gamerules.py)

2111 байт заголовка → zlib → нод-дерево GameRules/LordsRules (G4). Чтение и запись (образец корректной переупаковки — Lord Editor); наш модуль обязан давать round-trip на файле из поставки Lord Editor (`gamerules_fixed.dat`).

## 4.4. Сборка snapshot и diff

`snapshot_builder` сводит: lords (жив/мёртв, золото, честь, ранг, эстейты, войска), buildings (тип, позиция, владелец, % HP), estates (слот, тип, владелец, продукция), population, ресурсы. `diff_engine` сравнивает два snapshot'а и выдаёт события типов: `building_built|building_lost|battle|lord_died|estate_captured|troops_changed|population_changed`. Время событий — по позиции между snapshot'ами (интерполяция по автосейвам, если их несколько).

## 4.5. Честность (honesty/accounting.py)

Реализует контракт 3.9. Вход: стартовый и конечный snapshot'ы + scene_spec. Выход: отчёт с вердиктом. Отдельная функция `provision_balance(spec) -> bool` — равенство стартового провижининга ±10 % (проверяется ДО запуска сцены, генератор обязан её вызывать).

## 4.6. CLI

```
python -m sh2tw.cli parse <file.s2m|file.sh2> --out snap.json
python -m sh2tw.cli validate <file>            # round-trip: побайтовая идентичность
python -m sh2tw.cli validate-corpus <dir>      # по всем картам/сейвам; отчёт покрытия
python -m sh2tw.cli diff a.json b.json --out events.json
python -m sh2tw.cli honesty start.json end.json spec.json --out h.json
python -m sh2tw.cli catalog-maps <dir>         # реестр карт-заготовок (13, раздел E)
```

## 4.7. Тесты и приёмка

Тесты (pytest, `tests/`):

- **Корпус round-trip:** все 89 карт и 78 сейвов копии заказчика: `load → roundtrip_bytes() == исходные байты`. Допустимые падения на этапе 2 — 0 (сырые сегменты переносятся как есть; падение = баг контейнера).
- **Покрытие декодирования:** ≥ 95 % объектов MapHeader известных карт типизированы; метрика `coverage` в `validate-corpus`.
- **Мутационная устойчивость:** урезанные/битые файлы (отрезано 10/100/1000 байт) — парсер падает с `Sh2ParseError`, не зависает, не «зацикливает» память.
- **Детерминизм:** parse одного файла дважды — идентичный JSON (стабильная сортировка ключей).
- **AIC:** разбор всех 47 `.aic` игры; длина после сборки равна исходной; 4 «обрезанных тестовых» — помечены и пропускаются.
- **Честность:** юнит-тесты на синтетических парах snapshot'ов: чистый матч → pass; «+3000 золота из ниоткуда» → violation.

Критерии приёмки этапа (машинные):

1. `validate-corpus` по каталогу игры: 167/167 файлов round-trip OK (или каждая неудача объяснена в `QUESTIONS.md` с классификацией).
2. `parse` любого сейва даёт snapshot с `raw_unknown_objects` ≤ 15 % счётчика объектов.
3. `diff` пары сейвов «до/после победы» корректно даёт `lord_died` и смену владельцев эстейтов (проверено человеком на 3 реальных парах).
4. Все тесты pytest зелёные; время полного прогона корпуса ≤ 10 мин.

## 4.8. Известные ловушки

- **Четыре энума лордов (F9):** индексы лордов различаются между подсистемами (триггеры убийств и др.; официально задокументированные баги редактора: Olaf↔Player, Barclay↔Olaf). Парсер не «исправляет» энумы — сохраняет как есть + таблица соответствий в `ref/enums/` (заполняется в V8). Любая правка триггеров убийств — только через таблицу.
- **mapsize ≠ размер грида:** поле описывает класс/область (128/256 играбельных), backing-grid высот всегда 256×256 (F3).
- **Уровень zlib:** игра может читать и «не родной» уровень сжатия — но round-trip тест требует точного воспроизведения; сателлит `.meta.json` с уровнями — часть эталонов.
- **Сейвы различаются richer-состоянием:** `.sh2` содержит те же сегменты + runtime-данные; различия фиксировать по мере встречи (реестр фактов).
