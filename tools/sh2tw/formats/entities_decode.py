"""entities_decode.py — семантический разбор размещённых сущностей сегмента s2game (S2.5).

Что декодируется (доки OpenSH2 + сверка со ВСЕМ корпусом 23.11.2026:
70 .s2m + 89 здоровых .sh2, 928 377 объектов, падений обхода нет):

1. Entity field 0 (PlacedActors.md): «наследованное поле 0 Entity — упакованное
   тело 59 байт; байт on-map в теле по смещению 12, позиция XYZ — по 21/25/29».
   Кадрирование в payload подтверждено корпусом: последовательность
   [u32=0][u32=59][59-байтное тело] (паттерн 00 00 00 00 3B 00 00 00).
   X/Z в сырых единицах карты: мир = raw/1024 (PlacedActors.md «Map X/Z divide
   by 1024»), Y — в шкале высот рельефа, не подменяется sampling.
2. Building block (Buildings/Keep.md, Buildings/Overview.md): секция
   [A5 C1 FF FF][idx][необязательная регистрация int32=8 + 'Building']
   [int32=1][int32=52][тело 52 байта]. Поля тела (дока Keep.md, дословно
   подтверждена корпусом — позиции/поворот/размеры):
   +24 float X модели, +28 float высота, +32 float Z, +36 float поворот в
   градусах (корпус: только 0/90/180/270), +40 int32 ширина отпечатка (уже
   повёрнутой), +44 int32 высота. Небользованные uint16 по +19/+21 —
   SavedBuildingReference (CompositeBuildings.md: ссылка = (u16@19<<16)|u16@21;
   семантика глубже не верифицирована, поле отдаётся как есть).
   Позиция модели (Building block) авторитетнее позиции актёра: у поворотных
   строений они расходятся (Keep.md: «actor X 22, model X 31»).

ЧТО СОЗНАТЕЛЬНО НЕ РАЗБИРАЕТСЯ (UNKNOWN-принцип ТЗ 00/04; байты сохраняются
raw через ObjectNode payload — побайтовая реконструкция уже гарантирована S2.2):
- Поворот (heading) актёров: PlacedActors.md — heading читается ПОСЛЕ
  массивов переменной длины в полях Actor 0 и 2, «а не угадывается по
  фиксированному смещению» → не декодируем.
- Владелец/эстейт/команда (owner/estate/team) у актёров и построек: точных
  смещений в доках нет → не декодируем, не гадаем.
- Остальные ~606 281 объектов корпуса (ScriptAction, эмиттеры, кланы, слои,
  менеджер S2Player/S2Estate/BuildingLayer...) — raw: у них нет кадрируемых
  Entity-59 / Building-52 секций (или они не являются классами размещённых
  объектов).

Расхождения корпуса с доками (записаны, семантика НЕ додумана; счёт по всему
корпусу 23.11.2026 — карты .s2m + сейвы .sh2):
- Statue: 356 объектов, у 354 Building block валиден, но 2 экземпляра в
  war_chapter12.s2m (obj 0x1cbef608/0x1cbef518) имеют размеры отпечатка 0x0
  (дока Buildings/Overview.md требует положительные), координаты при этом
  валидные → класс целиком переведён в raw-passthrough
  (BUILDING_CLASS_BLOCKLIST); OpenSH2 BuildingAssetReview.md и так держит
  Statue в unresolved.
- SpiralStairTeleport: 3780 объектов в сейвах; у 3775 Building-52 кадра нет
  вовсе, у 5 кадр есть, но в полях размеров float-мусор → класс в блоклисте
  (дока Keep.md описывает Building block для обычных строений, layout
  телепортов расходится).
- Актёрские объекты без Entity-59 кадра (~0.05%): 16 Archer, 21 Outlaw,
  18 HorseCart, 14 Deer, 10 Rabbit... — остаются raw (no_frame).
- Два+ ВАЛИДНЫХ Entity-59 кадра в одном payload — позицию не выбираем, raw
  (multi_frame): 181 Archer, 81 Pikeman, 43 Spearman, 413 Baker (вероятно
  связанные сущности/живность у повозок), 41 HorseArcher...
- Кадр есть, но тело не проходит валидацию байта/координат — raw
  (invalid_frames): 9 HorseCart, 3 Knight, 2 Outlaw, 1 Rabbit...
- Ложные 8-байтные совпадения паттерна [0][59] в payload (Archer: ~184k
  объектов с 2+ СЫРЫМИ совпадениями) не считаются Entity field 0, пока не
  проходят валидацию корпуса (байт on-map + координаты поля карты).
- Кадр Entity-59 с длиной 0x40000000 вместо 59 встречается в неактёрских
  payload'ах (EmitterMgr/DangerLayer) — ложные совпадения, эти типы вне
  ACTOR_CLASSES (покрытие <90%).

ref/entities.csv в репозитории НЕТ; таблицы классов корпуса — ref/buildings.csv
и ref/unit_types.csv (категории/цены для downstream S2.6), идентификация класса
в этом модуле — структурная (по заголовку объекта object_tree), а не по CSV.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .object_tree import DATA_START, ObjectNode
from .s2m_file import Sh2ParseError

# --- классы, выверенные по полному корпусу (23.11.2026, 159 файлов) -----------
# Building block кадрируется РОВНО у 100% объектов этих классов (bld_one==total).
BUILDING_CLASSES = frozenset({
    "Apothecary", "AppleFarm", "ArmourerWorkshop", "Armoury", "Bakery", "BeeHive",
    "BlacksmithWorkshop", "Brewery", "CarterPost", "ChandlerWorkshop", "Church",
    "ConstructingBeacon", "ConstructingBridge", "ConstructingKeep",
    "ConstructingMonastery", "CourtHouse", "DairyFarm", "Dovecote", "Dungeon",
    "EngineersGuild", "Fairground", "FalconersPost", "FishPond", "FletcherWorkshop",
    "GardenersHut", "GongPit", "Granary", "HopFarm", "Hovel", "HuntersPost", "Inn",
    "IronMine", "Jousting", "Keep1", "Keep2", "Keep3", "Keep4", "KillingPit",
    "Kitchen", "Ladder", "LargeGateHouse", "ManTrap", "Market", "MediumGateHouse",
    "MercPost", "Mill", "Monastery", "MusiciansGuild", "OutlawCamp", "OxTether",
    "PigFarm", "PitchRig", "PoleturnerWorkshop", "SawPit", "ServantsQuarters",
    "SheepFarm", "SiegeCamp", "Signpost", "SmallGateHouse", "Smelter", "Solar",
    "Stables", "StockPile", "StoneBarracks", "StoneQuarry", "TannerWorkshop",
    "TortureBlock", "TortureBrandingChair", "TortureBurningPost",
    "TortureFloggingPost", "TortureGallows", "TortureGibbet", "TortureMask",
    "TortureRack", "TortureStocks", "TortureWheel", "TorturersGuild", "TowerGreat",
    "TowerLookout", "TowerRoundShort", "TowerRoundTall", "TowerSquare",
    "TowerStairwell", "Treasury", "TunnelHole", "VillageFlagPole", "Vineyard",
    "VintnerWorkshop", "WarHoundCage", "WatchPost", "WaterPot", "WeaverWorkshop",
    "Well", "WheatFarm", "WoodenGateHouse", "WoodenPlatform",
})
# Классы, где layout Building block расходится с докой на корпусе → raw (см. докстринг).
BUILDING_CLASS_BLOCKLIST: dict[str, str] = {
    "Statue": "2 из 356 экземпляров (war_chapter12.s2m) имеют размеры 0x0; дока "
              "Buildings/Overview.md требует положительные размеры",
    "SpiralStairTeleport": "0 валидных Building-52 кадров из 3780 (сейвы); в 5 "
                           "payload'ах кадр есть, но размеры содержат float-мусор",
}
# Entity-59 кадр (одиночный и валидный) минимум у 90% объектов этих классов.
ACTOR_CLASSES = frozenset({
    "AppleFarmer", "AppleTree", "Archer", "Armourer", "ArmedPeasant", "Arrow",
    "Assassin", "AxeThrower", "Ballista", "BallistaArrow", "Bailiff", "Baker",
    "Bear", "Berserker", "Blacksmith", "BoatWarrior", "Brazier", "Brewer",
    "BurningCart", "BurningLog", "BurningLogTipper", "Cat", "Catapult", "Carter",
    "CarterCart", "Child", "Chicken", "Chandler", "ConstructionMonk", "Cook",
    "CooksHelper", "Criminal", "Crow", "Crossbowman", "Cow", "Deer", "DairyFarmer",
    "Disease", "Dog", "Dolphin", "Engineer", "FairgroundActor", "Falcon",
    "Falconer", "FireBallista", "FireEater", "FishFarmer", "Fletcher", "Fox",
    "Gardener", "GrapeFarmer", "Grapes", "Goose", "Gong", "GongFarmer", "Healer",
    "Heron", "HopFarmer", "Hops", "Horse", "HorseArcher", "HorseArcherHorse",
    "HorseCart", "Hunter", "InnKeeper", "IronMiner", "Jester", "JoustingHorse",
    "JoustingKnight", "Judge", "Juggler", "Knight", "Ladderman", "Lady",
    "LightCavalry", "LightCavalryHorse", "Lord", "Maceman", "Mangonel",
    "Mantlet", "Minstrel", "Miller", "Monk", "Mother", "NobleLady", "NobleMan",
    "Outlaw", "OxHandler", "Oxen", "Page", "Peasant", "Pheasant", "Pig",
    "PigFarmer", "Pikeman", "PitchWorker", "Poleturner", "Priest", "Rabbit",
    "Rat", "RockMissile", "RockThrower", "SeaGull", "Shepherd", "Sheep", "Ship",
    "SiegeTowerLarge", "Spearman", "StoneMason", "StoneTipper", "Swordsman",
    "Tanner", "Torturer", "Trebuchet", "Vintner", "WarHound", "WarriorMonk",
    "Watchman", "Weaver", "WellWorker", "Wheat", "WheatFarmer", "Whale",
    "WorkerMonk", "Wolf", "WoodCutter",
})

# Entity field 0 (PlacedActors.md): [u32=0][u32=59] + 59-байтное тело.
ENTITY_FIELD0_FRAME = b"\x00\x00\x00\x00\x3b\x00\x00\x00"
ENTITY_BODY_LEN = 59
ONMAP_BYTE = 12          # смещение в теле 59B (дока)
POS_X, POS_Y, POS_Z = 21, 25, 29  # float32 XYZ в теле 59B (дока)
BUILDING_BODY_LEN = 52   # Keep.md: counted 52-byte Building body
BPOS_X, BPOS_Y, BPOS_Z, BYAW = 24, 28, 32, 36   # float, смещения в теле 52B
BW_ROT, BH_ROT = 40, 44  # int32 отпечаток (уже повёрнутый)
BLINK_HI, BLINK_LO = 19, 21  # uint16 unaligned (CompositeBuildings.md)
CELL = 1024.0            # сырых единиц на клетку карты (F3/PlacedActors)
MAP_CELLS_MAX = 256      # backing-grid высот 256x256 (F3)


def _finite(*vals: float) -> bool:
    return all(v == v and abs(v) != float("inf") for v in vals)


def find_entity_field0(payload: bytes) -> list[int]:
    """Смещения начала 59-байтного тела Entity field 0 в payload."""
    out: list[int] = []
    j = payload.find(ENTITY_FIELD0_FRAME)
    while j >= 0:
        b = j + 8
        if b + ENTITY_BODY_LEN <= len(payload):
            out.append(b)
        j = payload.find(ENTITY_FIELD0_FRAME, j + 8)
    return out


def find_building_bodies(payload: bytes) -> list[int]:
    """Смещения 52-байтного Building body (секция A5C1FFFF...[1][52], Keep.md)."""
    out: list[int] = []
    j = 0
    n = len(payload)
    while True:
        j = payload.find(DATA_START, j)
        if j < 0 or j + 16 > n:
            break
        d2 = struct.unpack_from("<I", payload, j + 8)[0]
        if d2 == 1 and struct.unpack_from("<I", payload, j + 12)[0] == BUILDING_BODY_LEN \
                and j + 16 + BUILDING_BODY_LEN <= n:
            out.append(j + 16)
        elif d2 == 8 and payload[j + 12:j + 20] == b"Building" \
                and struct.unpack_from("<II", payload, j + 20)[0:2] == (1, BUILDING_BODY_LEN) \
                and j + 28 + BUILDING_BODY_LEN <= n:
            out.append(j + 28)
        j += 4
    return out


@dataclass
class ActorPlacement:
    """Размещённый актёр/сущность по Entity field 0 (PlacedActors.md)."""
    obj_id: int
    class_name: str
    on_map_byte: int
    x_raw: float
    y_raw: float
    z_raw: float
    body_off: int
    node: ObjectNode = field(repr=False, default=None)  # type: ignore[assignment]

    @property
    def x_map(self) -> float:
        return self.x_raw / CELL

    @property
    def y_height(self) -> float:
        return self.y_raw

    @property
    def z_map(self) -> float:
        return self.z_raw / CELL

    def as_dict(self) -> dict:
        return {"id": self.obj_id, "class": self.class_name, "on_map": self.on_map_byte,
                "x": round(self.x_map, 6), "z": round(self.z_map, 6),
                "y_raw": self.y_raw, "rotation": "UNKNOWN(heading after variable "
                "arrays — PlacedActors.md)", "owner": "UNKNOWN(no documented offset)"}


@dataclass
class BuildingPlacement:
    """Строение по counted 52-byte Building block (Keep.md/Overview.md)."""
    obj_id: int
    class_name: str
    x_raw: float
    y_raw: float
    z_raw: float
    yaw_deg: float
    footprint_w: int   # уже повёрнутый отпечаток (Overview.md)
    footprint_h: int
    saved_ref: int     # (u16@19<<16)|u16@21 (CompositeBuildings.md), семантика не верифицирована
    body_off: int
    node: ObjectNode = field(repr=False, default=None)  # type: ignore[assignment]

    @property
    def x_map(self) -> float:
        return self.x_raw / CELL

    @property
    def z_map(self) -> float:
        return self.z_raw / CELL

    def as_dict(self) -> dict:
        return {"id": self.obj_id, "class": self.class_name,
                "x": round(self.x_map, 6), "z": round(self.z_map, 6),
                "y_raw": self.y_raw, "yaw_deg": self.yaw_deg,
                "w": self.footprint_w, "h": self.footprint_h,
                "saved_ref": f"0x{self.saved_ref:08x}",
                "owner": "UNKNOWN(no documented offset)"}


def _valid_actor_body(p: bytes, b: int) -> tuple[int, float, float, float] | None:
    """Корпус валиден? (PlacedActors.md: байт on-map @12 ∈ {0,1}, XYZ @21/25/29
    конечны и внутри поля карты). Возвращает (onmap, x, y, z) или None."""
    if p[b + ONMAP_BYTE] not in (0, 1):
        return None
    x, y, z = struct.unpack_from("<fff", p, b + POS_X)
    if not _finite(x, y, z):
        return None
    if not (0 <= x / CELL < MAP_CELLS_MAX and 0 <= z / CELL < MAP_CELLS_MAX and abs(y) < 65536):
        return None
    return p[b + ONMAP_BYTE], x, y, z


def decode_actor(node: ObjectNode, filename: str = "") -> tuple[ActorPlacement | None, str]:
    """По ОДНОМУ валидному Entity-59 кадру; иначе (None, причина).

    Классовый allow-list (ACTOR_CLASSES) — покрытие >=90% на корпусе. Кандидат
    кадра, не прошедший валидацию тела, НЕ считается Entity field 0 (ложное
    совпадение 8-байтного паттерна), поэтому «мусорные» последовательности в
    payload (Archer: ~184k объектов с 2+ сырыми совпадениями, из них <=2 с
    двумя ВАЛИДНЫМИ) не мешают единственному валидному кадру. Два+ валидных
    кадра — позиция не выбирается наугад, объект остаётся raw (multi_frame).
    """
    t = node.type_name
    if not t or t not in ACTOR_CLASSES:
        return None, "not_actor_class"
    offs = find_entity_field0(node.payload)
    if not offs:
        return None, "no_frame"
    valid = [(b, v) for b in offs if (v := _valid_actor_body(node.payload, b))]
    if len(valid) > 1:
        return None, "multi_frame"
    if not valid:
        return None, "invalid_frames"  # расхождение корпуса — raw, не исключение
    b, (onmap, x, y, z) = valid[0]
    return ActorPlacement(obj_id=node.obj_id, class_name=t, on_map_byte=onmap,
                          x_raw=x, y_raw=y, z_raw=z, body_off=b, node=node), "decoded"


def decode_building(node: ObjectNode, filename: str = "") -> tuple[BuildingPlacement | None, str]:
    """По одному одиночному валидному Building-52 кадру; иначе (None, причина).

    Один кадр, но тело не проходит строгую валидацию (размеры/поворот/координаты)
    → Sh2ParseError с именем файла и объекта: layout доки не сходится с байтами.
    Классы из BUILDING_CLASS_BLOCKLIST не декодируются вовсе (расхождение доки с
    корпусом уже задокументировано) → причина class_blocked.
    """
    t = node.type_name
    if not t or t in BUILDING_CLASS_BLOCKLIST:
        return None, "class_blocked" if t else "no_type"
    offs = find_building_bodies(node.payload)
    if not offs:
        return None, "no_building_frame"
    if len(offs) > 1:
        return None, "multi_building_frame"
    b = offs[0]
    p = node.payload
    x, y, z, yaw = struct.unpack_from("<4f", p, b + BPOS_X)
    fw, fh = struct.unpack_from("<ii", p, b + BW_ROT)
    ref = (int.from_bytes(p[b + BLINK_HI:b + BLINK_HI + 2], "little") << 16) | \
          int.from_bytes(p[b + BLINK_LO:b + BLINK_LO + 2], "little")
    who = f"{filename or '<имя не передан>'}: {t} obj 0x{node.obj_id:x}"
    if not _finite(x, y, z, yaw):
        raise Sh2ParseError(f"{who}: не-числовые XYZ/yaw в Building body @{b}")
    if not (1 <= fw <= 40 and 1 <= fh <= 40):
        raise Sh2ParseError(f"{who}: размеры отпечатка {fw}x{fh} вне 1..40 (дока: положительные)")
    if yaw % 90 != 0 or not (-720 <= yaw <= 720):
        raise Sh2ParseError(f"{who}: поворот {yaw} кратно 90 (корпус: 0/90/180/270) не выдержан")
    if not (0 <= x / CELL < MAP_CELLS_MAX and 0 <= z / CELL < MAP_CELLS_MAX and abs(y) < 65536):
        raise Sh2ParseError(f"{who}: позиция модели X/Z {x / CELL:.3f},{z / CELL:.3f} вне поля карты")
    return BuildingPlacement(obj_id=node.obj_id, class_name=t, x_raw=x, y_raw=y, z_raw=z,
                             yaw_deg=yaw, footprint_w=fw, footprint_h=fh, saved_ref=ref,
                             body_off=b, node=node), "decoded"
