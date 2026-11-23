"""snapshot_builder.py — сведение .s2m/.sh2 в детерминированный snapshot.json (S2.6).

Форма — контракт 03 §3.5 (schema_version/source/map/estates/buildings/census/
raw_unknown_objects); поле card S2.6 фиксирует модуль здесь (в перечне 04 §4.2
он значится под formats/ — импорт: from .snapshot_builder import parse_snapshot).

Только ДОКАЗАННОЕ из S2.1/S2.2/S2.4/S2.5 стека; ничего не догадываем:
- map/estate markers — map_header.decode_mapheader_segment (S2.4);
- buildings/actors/census/coverage — s2game.decode_s2game_nodes (S2.5),
  семантику декодеров модуль НЕ мутирует (только читает);
- lords, population, gold, game_time_months, owner_lord/hp_pct у строений,
  owner_lord/product у эстейтов, numeric type_id — явные null, причина каждого
  — в unknown_fields (UNKNOWN-принцип ТЗ 00; G18/S2.4: Scenario/Mission raw
  из-за расхождения доков OpenSH2 с exe 2020; owner/HP — нет документированных
  смещений, S2.5).

Детерминизм (байт-в-байт один файл → один JSON):
- snapshot_json(): sort_keys, фиксированный indent; списки размещений
  отсортированы по obj_id; счётчики — dict c сортировкой ключей;
- source.parsed_at по умолчанию = mtime исходного файла (UTC), а НЕ wall clock
  (иначе два раза подряд не совпадёт); override — параметр parsed_at ISO-строкой.

Сырые байты в JSON не пишутся (карточка S2.6; дампов нет). 04 §4.7 требует
только счётчик raw_unknown_objects — метрику покрытия; сырьё остаётся в
ObjectNode.payload (побайтовый round-trip гарантирован S2.2/S2.3). Связанные
дампы dump/ (03 §3.5) вне объёма S2.6 — завязаны на писатель/валидацию (05).
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .catalog_maps import display_map_name
from .formats import s2game as sg
from .formats.map_header import decode_mapheader_segment
from .formats.object_tree import parse_segment
from .formats.s2m_file import S2mFile, Sh2ParseError

SCHEMA_VERSION = "1.0"

# Причины каждого UNKNOWN-поля контракта 03 §3.5 (ключи — пути по JSON снимка).
UNKNOWN_FIELDS: dict[str, str] = {
    "lords": "Scenario/Mission/ScenarioEvent в mapheader — raw-passthrough: "
             "доки OpenSH2 расходятся с payload exe 2020 (факт G18, S2.4); "
             "жив/мёртв, золото, честь, ранг, войска — доказанных декодеров нет",
    "game_time_months": "документированного источника нет; int-опция file_header "
                        "'lastsave' семантически не верифицирована — не гадаем",
    "population": "нет документированного смещения (доки OpenSH2 не покрывают)",
    "resources.gold_total_estimated": "золото живёт в нераскодированном "
                                      "Scenario/состоянии эстейтов (см. lords)",
    "map.mapsize_class": "значение взято как есть из int-опции file_header "
                         "'mapsize' (128/256); семантика «класса» из примера "
                         "контракта (2) документами не подтверждена",
    "buildings[].type_id": "числового id в ref/buildings.csv нет; ref/entities.csv "
                           "(реестр id) в репозитории отсутствует — type_name из "
                           "структурной идентификации object_tree (S2.5)",
    "buildings[].owner_lord": "см. S2.5: owner/estate/team — нет документированного "
                              "смещения в PlacedActors.md/Buildings",
    "buildings[].hp_pct": "HP строений декодером не покрыт (доки не дают смещения)",
    "buildings[].rotation": "в buildings yaw_deg доказан (кратно 90°, S2.5); у actors "
                            "heading читается только после массивов переменной длины "
                            "(PlacedActors.md) — не декодируем",
    "actors[].owner_lord": "см. S2.5: owner — нет документированного смещения",
    "estates[].owner_lord": "EstateMarkers.md (S2.4): 396-байтный layout даёт только "
                            "slot/x/z/kind — владельца дока не описывает",
    "estates[].product": "продукция деревень в нераскодированном Scenario (G18)",
    "radarmap_segment": "сегмент radarmap — opaque raw-passthrough; декодера нет "
                        "(radar_map.py в 04 §4.2 вне объёма S2.6); это не узлы "
                        "object_tree, в raw_unknown_objects не входит",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_out_path(out: str | Path) -> Path:
    """Путь --out для CLI parse.

    Практическая уступка окружению: в git-bash аргумент '/tmp/...' приходит в
    нативный python3 как есть, и запись на '/tmp/...' ушла бы в C:\\mp. Строки,
    начинающиеся с '/tmp/' (или равные '/tmp'), разрешаем в системный временный
    каталог (tempfile.gettempdir()); остальные пути — без изменений.
    """
    s = str(out)
    if s == "/tmp" or s.startswith("/tmp/") or s.startswith("/tmp\\"):
        return Path(tempfile.gettempdir()) / s[len("/tmp"):].lstrip("/\\")
    return Path(out)


def snapshot_json(snap: dict) -> str:
    """Канонический JSON снимка: детерминированный порядок/отступ — тот же файл
    даёт байт-идентичный текст при повторном декоде."""
    return json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True)


def _building_row(bp: sg.ed.BuildingPlacement) -> dict:
    return {"obj_id": bp.obj_id, "type_name": bp.class_name, "type_id": None,
            "x": round(bp.x_map, 6), "z": round(bp.z_map, 6), "y_raw": bp.y_raw,
            "yaw_deg": bp.yaw_deg, "w": bp.footprint_w, "h": bp.footprint_h,
            "saved_ref": f"0x{bp.saved_ref:08x}",
            "owner_lord": None, "hp_pct": None, "rotation": "yaw_deg"}


def _actor_row(ap: sg.ed.ActorPlacement) -> dict:
    return {"obj_id": ap.obj_id, "type_name": ap.class_name,
            "x": round(ap.x_map, 6), "z": round(ap.z_map, 6), "y_raw": ap.y_raw,
            "on_map": ap.on_map_byte, "owner_lord": None, "rotation": None}


def build_snapshot(path: Path, parsed_at: str | None = None) -> dict:
    """Один файл (.s2m карта или .sh2 сейв — контейнер один, F1/F12) → snapshot.

    Исключения только от контейнера/обхода (S2mFile, parse_segment — «падать
    быстро», 04 §4.7). Семантический провал mapheader-декода (G18-риск на
    отдельных сейвах) НЕ роняет снимок: map/estates уходят в null, ошибка —
    в parse_errors (человек обязан её видеть).
    """
    path = Path(path)
    m = S2mFile.load(path)

    # --- s2game: перепись + размещения + покрытие (S2.5) ---
    seg_game = next((s for s in m.segments if s.name == "s2game"), None)
    if seg_game is None:
        raise Sh2ParseError(f"{path.name}: нет сегмента s2game")
    nodes, _tail = parse_segment(seg_game.decompressed)
    model = sg.decode_s2game_nodes(nodes, path.name)

    # --- mapheader: имя карты, тип, эстейт-маркеры (S2.4) ---
    map_sec: dict | None = None
    estates: list[dict] = []
    mh_census: dict[str, int] = {}
    mh_raw_objects = 0
    parse_errors: list[str] = []
    seg_mh = next((s for s in m.segments if s.name == "mapheader"), None)
    if seg_mh is None:
        parse_errors.append("mapheader: сегмент отсутствует")
    else:
        mh_nodes, _t = parse_segment(seg_mh.decompressed)
        mh_census = dict(sorted(Counter(n.type_name or "<без типа>"
                                        for n in mh_nodes).items()))
        try:
            dec = decode_mapheader_segment(mh_nodes)
        except Sh2ParseError as e:
            parse_errors.append(f"mapheader: {e}")
        else:
            hdr = dec["header"]
            ints = m.file_header.int_opts
            strs = m.file_header.string_opts
            map_sec = {
                "name": display_map_name(hdr.name),
                "map_type_name": hdr.map_type_name,
                "map_type_code": hdr.map_type,
                "container_type": strs.get("type"),
                "mapsize_class": ints.get("mapsize"),
                "maxplayers": ints.get("maxplayers"),
                "balanced": ints.get("balanced"),
                "version": ints.get("version"),
                "crossrefs_resolve": dec["crossrefs_resolve"],
            }
            estates = [{"marker_slot": mk.slot, "type": mk.kind_name,
                        "x": mk.x, "z": mk.z, "packed_loc": mk.packed_loc,
                        "owner_lord": None, "product": None}
                       for mk in dec["estate_markers"] if mk.kind != 0]
            # семантически в mapheader раскрыты только MapHeader и EstateMarkers
            # (S2.4); Scenario/Mission/ScenarioEvent/Trigger/Action — raw.
            mh_raw_objects = len(mh_nodes) - 2

    total = sum(model.census.values())
    decoded = len(model.buildings) + len(model.actors) + (1 if model.heightlayer else 0)
    snap: dict = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "file": str(path),
            "name": path.name,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            # parsed_at = mtime файла (не wall clock) — детерминизм двух декодов;
            # override параметром parsed_at (оболочка пишет время сцены).
            "parsed_at": parsed_at or datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
        },
        "container": {
            "file_header": m.file_header.as_dict(),
            "segments": m.as_dict()["segments"],
            "tail_len": len(m.tail),
            "roundtrip_ok": m.roundtrip_ok(),
        },
        "map": map_sec,
        "game_time_months": None,
        "lords": None,
        "buildings": sorted((_building_row(b) for b in model.buildings),
                            key=lambda r: r["obj_id"]),
        "actors": sorted((_actor_row(a) for a in model.actors),
                         key=lambda r: r["obj_id"]),
        "estates": estates,
        "resources": {"gold_total_estimated": None},
        "population": None,
        "census": {
            "s2game_objects_total": total,
            "s2game_types": {k: model.census[k] for k in sorted(model.census)},
            "placement_census": {k: model.placement_census()[k]
                                 for k in sorted(model.placement_census())},
            "decoded_buildings": len(model.buildings),
            "decoded_actors": len(model.actors),
            "heightlayer_decoded": model.heightlayer is not None,
            "coverage": round(model.coverage(), 6),
            "mapheader_types": mh_census,
            "mapheader_raw_objects": mh_raw_objects,
        },
        # метрика покрытия 04 §4.7: узлы s2game без семантики (raw-passthrough).
        # Узлы mapheader-сегмента учтены отдельно (mapheader_raw_objects),
        # чтобы raw_unknown_objects сходился с census-API s2game (S2.5).
        "raw_unknown_objects": total - decoded,
        "unknown_fields": dict(sorted(UNKNOWN_FIELDS.items())),
        "parse_errors": parse_errors,
    }
    return snap


def parse_snapshot(path: Path, out: Path | None = None,
                   parsed_at: str | None = None) -> dict:
    """Сигнатура 04 §4.2: parse_snapshot(path, out) -> Snapshot.

    out=None — только вернуть dict (CLI печатает сам); иначе — canonical JSON
    в out (каталоги создаются). Возвращает снимок всегда.
    """
    snap = build_snapshot(path, parsed_at=parsed_at)
    if out is not None:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(snapshot_json(snap) + "\n", encoding="utf-8")
    return snap
