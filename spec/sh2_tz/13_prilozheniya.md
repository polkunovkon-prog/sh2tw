# 13. Приложения: справочники

## A. Триггеры редактора (список sd2 HeavenGames, проверен 23.11.2026)

Нумерация внутренних ID — по [OpenSH2:Notes/FileFormats/S2M/MapHeaderSegment/Actions and Triggers] + hexdiff (V8/V9). Счёт «31 триггер» из плана — число внутренних энумов; в редакторе видно больше алиасов (47 наименований ниже). Колонка «наше использование» — только для проектных сцен.

| Триггер (редактор) | Внутреннее имя | Наше использование |
|---|---|---|
| Always | Always | стартовые события (ControlLordsAI в 1-ю минуту) |
| Gold Acquired / Goods Acquired / Honor Acquired | GoldAcquired, GoodsAcquired, HonorAcquired | условия сцен развития |
| Enemy Gold/Goods/Honor Acquired | Enemy*Acquired | гонка экономики (театры) |
| No Food in a Granary; No Gong/Rats/Criminals in Your Estates | NoFoodInGranary, NoGong…, NoRats…, NoCriminals | события-встряски |
| Attain Population | PopulationReached | цели сцен развития |
| No People Left | NoPeopleLeft | — |
| No Enemy on Map / No Enemy Troops on Map / No Enemy or Invasions Left | AnyEnemyOnMap…, NoEnemyOrInvasionsLeft | конец полевого боя |
| All Your Troops Dead | AllYourTroopsDead | разгром атакующего |
| Percent of Troops Lost | PercentTroopsKilled | порог отхода |
| Recruit Archers | GetXTroops | обучение-миссии (не наш случай) |
| Your Lord Dies | LordDies | Lose обороны |
| Lord Damaged | LordDamaged | — |
| All the Enemy Lords are Dead / Enemy Lord Dead | MultipleLordsDead, SpecificEnemyLordDies | Win штурма |
| Rescue Lord | RescueLord | — |
| Player Kills Lord X / Other Lord Kills Lord Y / Lord X Kills Lord Y | PlayerKillsLordX, OtherLordsKillsLordX, SpecificLordKillsLordX | Win с конкретным убийцей; ВНИМАНИЕ: энумы (F9, V8) |
| Destroy Outlaw Camp | OutlawCampDestroyed | — |
| Breach Enemy's Castle Walls | — | бонус-цели штурма |
| Get Some/Many Troops Close to Enemy Lord | — | — |
| Lift Siege | — | — |
| Enemies are Near a Marker | — | детект подхода волн |
| Current Quest Status / Quest Not Complete / Single Quest Complete / Number of Quests Complete / Quest Failed | QuestA/B/C-семейство | — |
| After Briefing | AfterBriefing (EnterBriefing-пара) | тайминг старта событий |
| No Messages Playing | NoMessagesPlaying | цепочки сообщений |
| Building Site Complete / Percent Complete | — | — |
| Control a Number of Estates | ControlNumEstates | Win захвата региона |
| No Bears/Wolves Left on Map | KillAllWolves-пара | — |

## B. События/действия редактора (sd2, проверено 23.11.2026)

| Событие (редактор) | Внутреннее имя | Параметры (что подтверждено) | Наше использование |
|---|---|---|---|
| Win / Lose | Win, Lose | — | исходы сцен |
| **Invasion** | Invasion | «near-exact numbers of troops, which player owns it, where it begins and attacks, who it is attacking/reinforcing, whether it repeats» (sd2, дословно) | армии атакующих; волны; провижининг канала B |
| Stop Invasion | StopInvasions | по игроку/повторяемости | стоп волн |
| Bear Attack / Wolf Invasion / Rat Invasion | BearAttack, WolfInvasion, RatInvasion | число, маркер | события-встряски |
| Create Criminals | CreateCriminals | — | — |
| Set Wolves to Defensive | SetWolvesToDefensive | — | — |
| Bad Weather; Wheat/Apple/Hop/Vine/Swine/Mad Cow болезни; Lost Sheep; Bumper Harvest | BadWeather, WheatDisease, AppleBlight, HopWeevil, VineRot, SwineFever, MadCowDisease, LostSheep, BumperHarvest | — | события кампании (перенос бедствий) |
| Maintain Minimum Food Level | MaintainMinimumFoodLevel | эстейт, уровень | боевые карты без «нет еды» |
| Plague of Rats / Gong Infestation / Start Fires / Set all Buildings on Fire / Witchcraft / Peasants Revolt! | PlagueOfRats, GongInfestation, Fire, SetAllBuildingsOnFire, Witchcraft, Protest | — | события кампании |
| Redirect Village Output | RedirectVillageOutput | флаги (баг редактора: source↔target меняются местами — OpenSH2 README) | — |
| Stop Resource Production | TurnIndustriesOnOff | — | — |
| Cap Resources | CapResources | — | — |
| Give Resources / Give Gold / Give Honor / Set Honor / Set Rank | GiveResources, GiveGold, GiveHonour, SetHonour, SetRank | суммы | военная казна; ранги |
| Set Allies | SetAllies | списки друзей/врагов/нейтралов | дипломатия в сцене |
| Move Lord / Move Ship | MoveLord, MoveShip | — | — |
| Take Enemy's Castle | TakeEnemyCastle | — | применение победы штурма |
| Convert Estate to Village | ConvertEstateToVillage | — | интеграция захваченного |
| Quest (Complete) / Quest Failed | Quest, QuestFailed | — | — |
| Enter Briefing | EnterBriefing | — | напоминание целей |
| Set Available Troop Types | SetAvailableTroopTypes | список типов | пул найма в сцене |
| Gong/Rat Production, Frequency of Disease, Crime Rate, Outlaw Production, Wolf Spawn Rate | GongProduction, RatProduction, DiseaseProduction, CrimeRate, OutlawProduction, WolfSpawnRate | уровни/off | чистота боевых сцен |
| Limit Weapon Production | LimitWeaponProduction | типы оружия | — |
| Set Number of Campfire Peasants | SetCampfirePeasants | число (0 не работает) | — |
| Building Sites | — | см. sd2-гайд | — |
| Give Lord Full Peasants | MaxOutPeasants | — | старт сцен |
| Kill Off all Wolves / Kill Off all Lords Troops | KillAllWolves, KillAllLordsTroops | — | — |
| **Control Lord's AI** | ControlLordsAI | лорд, вкл/выкл (по сроку) | AI-only (V1), театры, выключение слота игрока |
| Control Gatehouses | ControlGateHouses | — | — |
| AI Troops Charge if Aggressive | SuperAggressiveTroops | — | доктрина агрессии |
| AI Troops Retreat | AITroopRetreat | — | порог отхода (ген доктрины) |
| Pause Sieges | PauseSieges | — | мирные театры |
| Make Troops Super Aggresive | SuperAggressiveTroops-пара | — | см. выше |
| Time until Final Invasion | TimeUntilFinalInvasion | месяцы | тайм-аут сцены |

## C. Энумы лордов (заполняется по V8)

Четыре энума с разными смещениями (F9). Известные задокументированные баги (OpenSH2 README): триггер «Other Lord Kills» показывает Olaf как «Player»; «Specific Lord Kills» путает Barclay↔Olaf, Olaf↔Player; Redirect Village Output меняет местами флаги. Шаблон таблиц (`ref/enums/`):

```
enum_id, context (trigger|action|scenario|estates), player_at (0|1|21?), lord_name, lord_portrait_file, notes
```

Заполнение: V8 (тест-карты всех пар + hexdiff). До заполнения триггеры убийств в генераторе ЗАПРЕЩЕНЫ (кроме проверенных на тест-карте).

## D. Юниты и стоимости (fandom Barracks/SH2, проверено 23.11.2026)

| Юнит | Золото | Честь | Снаряжение | unit_value (старт) |
|---|---|---|---|---|
| Вооружённый крестьянин | 5 | — | — | 5 |
| Копейщик | 8 | — | копьё | 20 |
| Лучник | 12 | — | лук | 30 |
| Пехотинник (maceman) | 20 | 1 | булава + кожаная броня | 45 |
| Арбалетчик | 20 | 2 | арбалет + кожаная броня | 55 |
| Пикинёр | 20 | 2 | пика + металлическая броня | 60 |
| Мечник | 40 | 8 | меч + металлическая броня | 110 |
| Рыцарь | 200 | 50 | меч + броня + конь | 400 |

`unit_value` = золото + честь×10 + снаряжение×2 (стартовые веса; финальные — после замеров в игре, задача S2.0; снаряжение из мастерских). Наёмный пост: юниты только за золото (ассасины и др. — «most expensive unit in gold and honour» — юнит-гайд SH2); полный список и цены снять в игре (V7c). Лимит юнитов: ~550 на сторону при 2 сторонах (G6).

## E. Реестр карт-заготовок (заполняется задачей S3.0)

Из копии заказчика: 89 файлов (70 .s2m + 19 .s2c: 30 kingmaker, 25 warcampaign, 19 historical, 8 freebuild, 7 peacecampaign). Форма реестра: `id, file, type, mapsize, lords, estates, markers_1..8 (расставил человек), роль (field|siege|defense|theater), sha256`. Кандидаты стартового отбора: Strong and Stable, Two Pronged Crown, Whitebear (план, этап 0). Отбор на живую проверку: 2 полевые, 3 штурмовые, 2–3 театральные, 1–2 специальные.

## F. Формат .aic (F4, сводка)

Длина `2928 + 8×N`; записи построек: (kind, локальные X/Z, поворот | group, param); 50 general values (семантика — дифф-протокол 08 §8.6); 24 списка × 10 точек; 10 групп × 20 точек; 240 флагов; точки `Z*100+X`; донжоны: 20 деревянный … 23 большой. Семантика планов (F5): все Castle Structure/Military постройки обязан содержать план (нет казармы — не построит); фермы/склады ИИ добавляет сам; приоритеты 1–255; несколько планов у лорда — выбор случайный (лишние переименовывать).

## G. gameRules.dat — честные поля правки (G4/G5)

Контейнер: 2111 байт → zlib → нод-дерево GameRules/LordsRules. База: `gamerules_fixed.dat` (Lord Editor v1.4: фикс осад Короля/Ястреба, копейщиков Быка). Честные поля Lord Editor: торговые веса, приоритеты найма, предпочтения построек, оборонительные группы, спавн преступности/гноя/крыс для ИИ-лордов (дисциплина мира). ЗАПРЕЩЕНО: стартовые ресурсы, скрытые доходы, «бонусные» веса AI Overhaul. Round-trip — обязателен (04 §4.3).

## H. Чек-лист честности (перед каждым матчем)

- [ ] `provision_balance(spec)`: стартовый провижининг сторон ±10 %.
- [ ] У ИИ нет Invasion-подкреплений, не оплаченных доктриной (все волны — из genome).
- [ ] После матча: `honesty_report.json` сформирован; `verdict == pass`.
- [ ] Нарушение → матч в карантин (`ga_runs/…/quarantine/`), доктрина не в элиту.

## I. Механика эстейтов (fandom Estate, проверено 23.11.2026)

Покупка деревни: 100 чести. Захват: войска у флага + очистка окрестности от военных юнитов врага; отсчёт **от 2000**; враг вернулся — пауза/сброс. Налог: **+50 золота/месяц** с эстейта. Смерть лорда: войска/постройки исчезают, эстейты переходят убийце; деревня-эстейт «оживает» по унаследованному шаблону; замковый эстейт (custom skirmish) наследует шаблон замка и пытается отстроиться. Деревни: 2 яблоневых сада, сток/амбар/флаг, картерский пост (40 единиц владельцу), производят луки/копья/мечи. Максимум сторон в сессии: 8.

## J. Реестр фактов (свод §2 плана + пополнение 23.11.2026)

Слои: ✓ — подтверждено первоисточником; ~ — из отчётов, согласуется; ? — требует эксперимента; ✗ — заблуждение.

| ID | Факт | Слой | Обновление 23.11.2026 |
|---|---|---|---|
| F1 | .s2m/.sh2: ASCII-заголовок + 3 zlib-сегмента (MapHeader, RadarMap, S2Game) | ✓ | Overview.md перечитан: порядок и маркеры подтверждены |
| F2 | Маркеры дерева объектов AF 1E / AD DE / A5 C1; «1E AB A1 5C» — ошибка | ✓ | — |
| F3 | Высоты 256×256 жёстко; mapsize — класс, не грид | ✓ | — |
| F4 | .aic = 2928+8N, структура по AIC.md | ✓ | — |
| F5 | План обязан содержать военные постройки; приоритеты 1–255 | ~ | — |
| F6 | Триггеры/действия: полный редакторский список снят со sd2 (47 триггеров/59 событий имен) | ✓ | СПИСОК ОБНОВЛЁН (Приложения A/B); внутренние ID — V8/V9 |
| F7 | Состояние мира переносится между миссиями одной карты | ✓ | — |
| F8 | EstateMarkers/Scenario/Mission/EstateStartupTroopPlacement — в MapHeaderSegment | ~→✓ | Состав папки MapHeaderSegment подтверждён (список файлов; содержимое читает агент из клона) |
| F9 | 4 энума лордов; баги редактора убийств | ✓ | Продублировано баг-листом OpenSH2 README |
| F10 | .gr2 не шифрованы (Granny v6); packfile — кэш | ✓ | — |
| F11 | .s2c не исследован — не используем | ~ | — |
| F12 | Сейв → карта (rehost) | ? | Остался ?: V4. Оговорка: контейнер одинаков, runtime-блоки — под вопросом |
| G1 | 8 сторон; покупка 100 чести; флаг-отсчёт 2000; +50 з/мес; смерть лорда | ✓ | fandom Estate перечитан — все числа подтверждены |
| G13 | Экземпляр заказчика: exe совпадает со Steam v1.5.0 — PE TimeDateStamp 0x5EA311C0 (2020-04-24 16:20 UTC) и размер 14 208 000 B == эталон docs sh2-unofficial-patch; version-ресурс переписан репакером на 5.1.0.0 (string-таблица пуста) — на паттерн-поиск не влияет; SteamLib.dll (ts 2017-10-06, 27 КБ) — Steam-эмулятор репака, Steam-клиента нет; папка v02.11.2022 = дата репака. md5 exe 5ba5b2637caa46aded4e0e76cc01efef, crc32 0xC50A196D (для V5/S1.2) | ✓ | замер агента 23.11.2026 (PE-заголовок, version-ресурс) + docs/bugs/*.md патча (эталон v1.5.0: FileVersion 1.5.0.0, ts 0x5ea311c0) |
| G14 | Синтаксис ASCII-заголовка .s2m/.sh2 подтверждён пробой на 6 файлах (TableStr/Int по доке FileHeader.md, UTF-16LE значения; mapsize опционален). После 3-го zlib-сегмента у части файлов есть двоичный трейлер (0–11119 B, не zlib — напр. «(M1) Escape Home» 52 B, war_chapter8 11119 B): переносится как есть (tail_raw). RadarMap-сегмент во всех проверенных 4 картах одинаковой распакованной длины 327820 B | ✓ | probe-замер агента 23.11.2026 на картах игры и сейвах заказчика |
| G15 | Дерево объектов сегментов: каждый сегмент предваряется magic-парой (0x5CA1AB1E,1) перед первым объектом; реестр типов ЛОКАЛЕН на сегмент; запись=[id][reg], для нового reg далее [len][name][parent-slot]; цепочка родителей пишет [reg][len][name]-записи только для ЕЩЁ НЕ зарегистрированных предков, стоп-условие слота: свой reg / 0 / уже зарегистрированный reg; payload до AF1EFFFF, сегмент до ADDEFFFF; ВНУТРИ payload бывают [A5C1FFFF][reg][len][name]-регистрации (пример: S2Clan reg151, TroopClan reg152 в клановом payload «9 миссия...»), их обязан собирать harvest-проход (избыточный сбор безвреден для байтовых границ, недостаточный — ломает обход); payload HeightLayer ограничен НЕ маркером, а объявленными длинами (3 407 932 B + hdr_len−12; фикстура sample.s2m — 3 408 172), внутри плоскостей углов реально встречается ложный паттерн AF1EFFFF — маркерный поиск по нему drift'ит (корпусные обломы war_chapter11/TheNewFrontier/Карта4 до фикса) | ✓ | обход+recon-идентичность на живом корпусе (70/70 карт + 89/95 сейвов, включая Saves/Restarts/), pytest tests/test_object_tree.py 23 passed, 23.11.2026 |
| G16 | 6 сейвов корпуса физически биты (byte rot: первый байт END_OBJ AF↛D0/AB; у 89 здоровых сейвов таких маркеров ровно 0): dsf.sh2, dsfg.sh2, аепгл.sh2, выяап.sh2, ыП.sh2 (Saves/) и «9 миссия..._Restart_1.sh2» (Saves/Restarts/). Внесены в tests/corpus/corrupt_saves.txt; парсер обязан на них падать громко (Sh2ParseError), не чинить молча. Подпапка Saves/Restarts/ (17 файлов фичи рестартов) — часть корпуса | ✓ | подсчёт маркеров агентом 23.11.2026 + test_corrupt_list_is_actually_corrupt |
| G17 | MapHeader (payload сегмента mapheader): [u32 0][u32 4][u32 id EstateMarkers][u32 1][u32 4][u32 id Scenario][u32 2][u32 L=длина блока имени с END][u32 C=символов UTF-16LE включая ведущий `\`][имя UTF-16LE][1B unk][u32 type: 0 kingmaker/2 war custom/3 peace custom/4 free build] + END; кросс-id резолвятся в объекты того же сегмента на всех 70 картах. EstateMarkers: payload ровно 396=[0][388=длина поля][32][32x{u32 packed_loc,i16 x,i16 z,u32 kind 0/1/2}][u32 0], запись i = имение i; war_chapter1 имение1=(151,29,kind2), war_chapter8 замки {1,2,3,10,11} деревни {4..9} — дословно по доку OpenSH2 | ✓ | pytest tests/test_map_header.py по всему корпусу, 23.11.2026 |
| G18 | Документация OpenSH2 по Scenario/Mission/ScenarioEvent НЕ совпадает с payload'ами exe 2020-11-04: Scenario начинается [0][N][1][id...] вместо [0C][count]; у ScenarioEvent 0x1A лежит на смещении 16, а не 0, action-id в позиции документа не резолвится в Actions сегмента (выборка chapter1). Это согласуется с собственной оговоркой Scenario.md про «modern counted tagged arrays». Решение: эти три типа идут raw-passthrough (побайтовый round-trip уже гарантирован S2.2/S2.3), доразбор — через живой вечер/эксперименты (V), не блокирует оболочку | ✓ | пробник 23.11.2026 по корпусу (1060 ScenarioEvent, 105 Mission, 70 Scenario) |
| G2 | 1 месяц ≈ 1 минута; скорость `+/−` numpad | ~ | Клавиши подтверждены (SH2 Heaven Shortcuts); множитель — V5b |
| G3 | Ванильный ИИ: найм от 200 золота; сила = .aic+gameRules+скрипты | ✓ | — |
| G4 | gameRules.dat 2111→zlib→дерево | ✓ | — |
| G5 | Lord Editor v1.4 + gamerules_fixed | ✓ | Тема 1263 (08.11.2025) подтверждает фиксы; страница файла 758 → 404 |
| G6 | sh2-unofficial-patch v0.9.0 (22.11.2026), Unlicense, Steam v1.5.0, d3d9-прокси, chain, конфиг, оверлей | ✓ | README перечитан; «save engine working» подтверждён |
| G7 | AI Overhaul v4.9-test1 без live-тестов; часть профилей даёт золото | ✓ | Решение ТЗ: полностью исключён (12 §12.2-4) |
| G8 | MP AI Enabler — для MP; нам не нужен | ✓ | — |
| G9 | Workshop ~2250; стратегический слой никто не делал | ~ | — |
| G10 | Репак «v02.11.2022» — вероятно, событие; сверка V5 | ~ | — |
| G11 | Скрытые бонусы ИИ в ванили обсуждались | ~ | Протокол честности обязателен |
| G12 | Копия: 89 карт, 47 .aic, 3361 .gr2, ~78 сейвов; ассоциаций нет | ✓ | — |
| N1 | НОВОЕ: OpenSH2 — коммит 05.11.2026, 105 коммитов; .s2m реализован; AI частично; Lua обещан | ✓ | github.com/nox7/OpenSH2 |
| N2 | НОВОЕ: юнит-опыт в SH2 отсутствует; ветеранство — на стороне оболочки | ✓ | fandom Barracks/SH2 |
| N3 | НОВОЕ: наёмный пост в SH2 существует (юниты за золото) | ✓ | fandom Mercenary Post/SH2; детали — V7c |
| N4 | НОВОЕ: Invasion позволяет задать владельца войск и цель (attack/reinforce) | ✓ | sd2, дословно |
| N5 | НОВОЕ: Definitive Edition Crusader (02.2026) — не SH2; SH2-ремастер не анонсирован | ✓ | поиск 23.11.2026 |

## K. Источники (проверены 23.11.2026, кроме отмеченных)

1. github.com/nox7/OpenSH2 — README (баги энумов, статус), Notes/FileFormats/** (комплект доков формата; клонируется в `ref/`).
2. github.com/B1naryVision/sh2-unofficial-patch — README v0.9.0; docs/features/{dll-chaining,settings-overlay,configuration}.md; docs/architecture.md.
3. stronghold2.heavengames.com/sd/sd2/ — «Triggers and Events» (Wahnsinniger; полный список с описаниями).
4. stronghold2.heavengames.com/sd/sd3/ — перенос состояния между миссиями (в плане).
5. stronghold-nation.com/forums/topic/1263 — Lord Editor Content Highlight (08.11.2025).
6. stronghold-nation.com/downloads/file/758 — страница загрузки (план; сейчас 404, замена — тема 1263).
7. stronghold.fandom.com/wiki/Barracks/Stronghold_2 — найм и стоимости юнитов.
8. stronghold.fandom.com/wiki/Mercenary_Post/Stronghold_2 — наёмный пост (существует; юниты за золото).
9. stronghold.fandom.com/wiki/Estate — механика эстейтов (100/2000/50).
10. fandom: Honor, Kingmaker, «Stronghold 2 — AI mechanics», Hotkeys (в плане, ✓-слой).
11. steamcommunity.com/app/40960/discussions/ — треды unofficial patch (23.05.2026), MP AI (2022).
12. arXiv 1803.02943 / 1803.10314 / 1803.10288 — методология GA (в плане).
13. Прочие из плана §«Источники» — без изменений.

## L. Правила имён и кодировок

- Карты генератора: `S2TW_<scene_id>_<type>.s2m` (≤27 символов имени); снимки: `snap_<scene_id>_{start|end}.json`; театры: `snap_theater_s<season>.json`; патчи: `<template_id>.patch.json`; доктрины: `doc_<архетип>_v<N>.yaml`; сейвы истории: `state_<season>_<n>.json`.
- Кодировки: все текстовые файлы проекта — UTF-8; данные игры — bytes; команды CLI — на английском; UI, журналы, комментарии — русский.
- Запрещены в идентификаторах: кириллица, пробелы, `#`, `%`, символы вне ASCII (имена файлов карт — только из `[A-Za-z0-9_]` после префикса, потому что список карт в игре капризен к локали — проверить на V12).
