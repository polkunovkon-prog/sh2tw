"""map_header.py — семантический разбор сегмента mapheader (S2.4).

Что доказано на корпусе (70 .s2m, 23.11.2026) и поэтому декодируется:
- MapHeader: [u32 unk][u32 id EstateMarkers][u32][u32][u32 id Scenario]
  [u32 enum=2][u32 L=длина блока имени с END-маркером][u32 C=число
  UTF-16LE символов имени, включая ведущий обратный слэш][имя UTF-16LE]
  [1 байт unk][u32 map type: 0=kingmaker,2=war custom,3=peace custom,
  4=free build] + END маркер. Кросс-ссылки id разрешаются в тот же
  сегмент (проверено на всех 70 картах, pytest).
- EstateMarkers: payload ровно 396 = [u32=0][u32=388=длина поля][u32=32]
  [32 записи x 12 байт: u32 packed_loc, i16 x, i16 z, u32 kind
  (0 нет, 1 деревня, 2 замок)] [u32 трейлер=0]. Запись i = имение i.
  Фикстуры: war_chapter1 имение1=(151,29,kind2); war_chapter8 замки
  {1,2,3,10,11}, деревни {4..9} — совпало с документом OpenSH2 дословно.

Что сознательно НЕ декодируется (raw-passthrough, UNKNOWN-принцип ТЗ 00):
- Scenario/Mission/ScenarioEvent: документ OpenSH2 (fixed-16 legacy)
  расходится с payload'ами exe 2020-11-04 (Scenario: observed u32
  [0][8][1][id]..., не [0C][count]; ScenarioEvent: 0x1A не в начале,
  кросс-ccылка action-id в позиции документа не бьётся). Байты
  сохраняются как есть; границы — payload из object_tree (round-trip
  побайтовый уже обеспечен S2.2/S2.3). Доразбор — отдельная задача
  V-замеров, не блокирует оболочку (оболочке нужны EstateMarkers +
  MapHeader, ТЗ 07 §estate-каркасы).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .object_tree import ObjectNode, Sh2ParseError

MAP_TYPES = {0: "kingmaker", 2: "war_custom", 3: "peace_custom", 4: "free_build"}
MARKER_KINDS = {0: "inactive", 1: "village", 2: "castle"}


@dataclass
class EstateMarker:
    slot: int
    packed_loc: int
    x: int
    z: int
    kind: int

    @property
    def kind_name(self) -> str:
        return MARKER_KINDS.get(self.kind, f"UNKNOWN({self.kind})")


@dataclass
class MapHeaderInfo:
    estate_markers_id: int
    scenario_id: int
    name: str
    name_raw: bytes
    map_type: int
    map_type_name: str
    node: ObjectNode  # raw-passthrough для побайтовой реконструкции


def decode_estate_markers(node: ObjectNode) -> list[EstateMarker]:
    p = node.payload
    if len(p) != 396:
        raise Sh2ParseError(f"EstateMarkers: payload {len(p)} != 396 (obj {node.obj_id})")
    u0, field_len, count = struct.unpack_from("<III", p, 0)
    if field_len != 388 or count != 32:
        raise Sh2ParseError(f"EstateMarkers: field_len={field_len} count={count}, ожидали 388/32")
    out: list[EstateMarker] = []
    for i in range(count):
        loc, x, z, kind = struct.unpack_from("<ihhI", p, 12 + i * 12)
        if kind not in MARKER_KINDS:
            raise Sh2ParseError(f"EstateMarkers slot {i}: kind {kind} вне {set(MARKER_KINDS)}")
        out.append(EstateMarker(i, loc, x, z, kind))
    # трейлер-у32 = 4 последних байта payload
    (trailer,) = struct.unpack_from("<I", p, 392)
    if trailer != 0:
        raise Sh2ParseError(f"EstateMarkers: трейлер {trailer} != 0")
    return out


def decode_map_header(node: ObjectNode) -> MapHeaderInfo:
    p = node.payload
    if len(p) < 42:
        raise Sh2ParseError(f"MapHeader: payload {len(p)} слишком короткий")
    u0, f4, em_id, f1, f4b, sc_id, scen_enum = struct.unpack_from("<7I", p, 0)
    # эмпирически на 70 картах: [0][4][idEM][1][4][idSC][2][L][C chars]...
    if scen_enum != 2 or f4 != 4 or f1 != 1 or f4b != 4:
        raise Sh2ParseError(
            f"MapHeader: преамбула {[f4, f1, f4b, scen_enum]} != [4,1,4,2] "
            f"(obj {node.obj_id})")
    block_len, n_chars = struct.unpack_from("<II", p, 28)
    name_bytes = p[36:36 + 2 * n_chars]
    if len(name_bytes) != 2 * n_chars:
        raise Sh2ParseError("MapHeader: имя выходит за payload")
    tail_off = 36 + 2 * n_chars
    if tail_off + 5 != len(p):
        raise Sh2ParseError(
            f"MapHeader: хвост {len(p) - tail_off} != 5 байт (1 unk + u32 type); "
            f"n_chars={n_chars} block_len={block_len}")
    map_type = struct.unpack_from("<I", p, tail_off + 1)[0]
    if map_type not in MAP_TYPES:
        raise Sh2ParseError(f"MapHeader: map type {map_type} вне enum")
    name = name_bytes.decode("utf-16-le", errors="replace")
    return MapHeaderInfo(
        estate_markers_id=em_id, scenario_id=sc_id,
        name=name, name_raw=name_bytes,
        map_type=map_type, map_type_name=MAP_TYPES[map_type], node=node)


def decode_mapheader_segment(nodes: list[ObjectNode]) -> dict:
    """Собирает семантику mapheader-сегмента; непройденные типы — raw."""
    by_type: dict[str, list[ObjectNode]] = {}
    for nd in nodes:
        by_type.setdefault(nd.type_name or "<аноним>", []).append(nd)
    if len(by_type.get("MapHeader", [])) != 1 or len(by_type.get("EstateMarkers", [])) != 1 \
            or len(by_type.get("Scenario", [])) != 1:
        raise Sh2ParseError(
            f"mapheader-сегмент: MapHeader/EstateMarkers/Scenario ожидается по 1, "
            f"найдено {[ (t, len(v)) for t, v in sorted(by_type.items()) if t in ('MapHeader','EstateMarkers','Scenario') ]}")
    hdr = decode_map_header(by_type["MapHeader"][0])
    markers = decode_estate_markers(by_type["EstateMarkers"][0])
    obj_ids = {nd.obj_id for nd in nodes}
    refs_ok = hdr.estate_markers_id in obj_ids and hdr.scenario_id in obj_ids
    return {
        "header": hdr,
        "estate_markers": markers,
        "crossrefs_resolve": refs_ok,
        "opaque": {t: by_type[t] for t in
                   ("Scenario", "Mission", "ScenarioEvent", "Trigger", "Action")
                   if t in by_type and not t.endswith(("Trigger", "Action"))},
        "actions_triggers_raw": [nd for t in by_type
                                 if (t.endswith("Trigger") or t.endswith("Action"))
                                 for nd in by_type[t]],
    }
