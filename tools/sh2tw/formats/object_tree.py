"""Дерево объектов сегмента (ТЗ 04 §4.3, F2).

Синтаксис: ref/OpenSH2-Notes/FileFormats/S2M/Object.md + Overview.md.
Маркеры: AF 1E FF FF — конец объекта; AD DE FF FF — конец сегмента.
Для первого объекта MapHeader-сегмента id+enum читаются дважды (Overview).
Неизвестные типы сохраняются сырыми (RawObject-модель): raw сохраняет точные
байты префикса записи и payload → реконструкция сегмента побайтна.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .s2m_file import Sh2ParseError

END_OBJ = b"\xaf\x1e\xff\xff"
DATA_START = b"\xa5\xc1\xff\xff"  # маркер начала данных
END_SEG = b"\xad\xde\xff\xff"
MAX_TYPE_NAME = 2048
MAX_CHAIN_DEPTH = 16




@dataclass
class ObjectNode:
    obj_id: int
    reg_index: int
    type_name: str | None
    chain: list[tuple[int, str]] = field(default_factory=list)  # (reg,name) предков
    header: bytes = b""  # точные байты: id(+двойной id)+reg+записи типов
    payload: bytes = b""  # байты после записей до маркера конца объекта
    has_end_marker: bool = True

    def as_dict(self) -> dict:
        return {"id": self.obj_id, "reg": self.reg_index, "type": self.type_name,
                "chain": self.chain, "payload_len": len(self.payload)}

    def reconstruct(self) -> bytes:
        out = self.header + self.payload
        if self.has_end_marker:
            out += END_OBJ
        return out


def _i32(seg: bytes, off: int) -> int:
    if off + 4 > len(seg):
        raise Sh2ParseError("усечение: нет 4 байт под int")
    return struct.unpack_from("<i", seg, off)[0]


def _looks_like_parent_slot(seg: bytes, i: int, reg: int, types: dict[int, str]) -> bool:
    """Похож ли dword в i на очередной слот предка цепочки, а не на payload."""
    if i + 8 > len(seg):
        return False
    nxt = _i32(seg, i)
    if nxt == 0 or nxt == reg or nxt in types:
        return True
    ln = _i32(seg, i + 4)  # продолжение цепочки: за слотом идёт [len][имя]
    if 1 <= ln <= MAX_TYPE_NAME and i + 8 + ln <= len(seg):
        cand = seg[i + 8:i + 8 + ln]
        try:
            s = cand.decode("ascii")
        except UnicodeDecodeError:
            return False
        return s.isalpha()
    return False


def _harvest_inline_registrations(payload: bytes, types: dict[int, str]) -> None:
    """Регистрации типов внутри data-подблоков payload ([A5C1FFFF][reg][len][имя]).

    Игра при чтении polymorphic-полей регистрирует эти reg'ы; без сбора
    последующие объекты с тем же reg ошибаются как «новые» (факт корпуса:
    S2Clan reg=151, TroopClan reg=152 внутри payload клана). Over-harvest
    безвреден для границ (bytes payload абсорбирует), under-harvest ломает.
    """
    j = 0
    while True:
        j = payload.find(DATA_START, j)
        if j < 0 or j + 12 > len(payload):
            return
        reg = _i32(payload, j + 4)
        ln = _i32(payload, j + 8)
        if 2 <= ln <= MAX_TYPE_NAME and j + 12 + ln <= len(payload):
            name = payload[j + 12:j + 12 + ln]
            try:
                txt = name.decode("ascii")
            except UnicodeDecodeError:
                txt = ""
            if txt.isidentifier() and reg not in types:
                types[reg] = txt
        j += 4


def _heightlayer_payload_end(seg: bytes, start: int) -> int:
    """Граница payload HeightLayer по объявленным длинам (HeightLayer.md, F3).

    payload = [tag=3][hdr_len][hdr_payload][A5C1FFFF][typeval][1][prim 0x40004]
    [65536 floats][tag2][3145740][3*(count+65536*4f)]; обычный payload
    3 407 932 B (hdr_len=12), chapter5 — 76 (+64). END-маркер НЕ искать
    (в плоскостях углов встречается ложный паттерн AF 1E FF FF — факт корпуса).
    """
    tag, hdr_len = _i32(seg, start), _i32(seg, start + 4)
    if tag != 3 or not 4 <= hdr_len <= 4096 or start + 8 + hdr_len + 8 > len(seg):
        raise Sh2ParseError(f"HeightLayer: подозрительный заголовок tag={tag} hdr={hdr_len}")
    marker_at = start + 8 + hdr_len
    if seg[marker_at:marker_at + 4] != DATA_START:
        raise Sh2ParseError("HeightLayer: нет маркера данных A5C1FFFF по смещению")
    total = (hdr_len - 12) + 3407932 if hdr_len >= 12 else 3407932
    end = start + total
    if end + 4 > len(seg) or seg[end:end + 4] != END_OBJ:
        raise Sh2ParseError("HeightLayer: вычисленная граница не сходится с END_OBJ")
    return end


def parse_segment(seg: bytes, first_double: bool | None = None) -> tuple[list[ObjectNode], bytes]:
    """Обход распакованного сегмента. Возвращает (узлы, остаток до END_SEG).

    Reconstruction-инвариант: b"".join(n.reconstruct() for n in nodes) + END_SEG
    == seg (при корректном разборе). Первый объект каждого сегмента предваряется
    magic-парой (0x5CA1AB1E, 1) — G15 (файлы игры authoritative).
    """
    nodes: list[ObjectNode] = []
    types: dict[int, str] = {}
    seen_ids: set[int] = set()
    i = 0
    magic_prefix = b""
    if first_double is not False and len(seg) >= 8 and _i32(seg, 0) == 0x5CA1AB1E:
        magic_prefix = seg[0:8]
        i = 8
    while i + 4 <= len(seg):
        if seg[i:i + 4] == END_SEG:
            return nodes, seg[:0] if i + 4 == len(seg) else seg[i + 4:]
        node_start = i
        obj_id = _i32(seg, i); i += 4
        reg = _i32(seg, i); i += 4
        if node_start == 0 and magic_prefix:
            pass  # уже смещены
        type_name: str | None = None
        chain: list[tuple[int, str]] = []
        if reg in types:
            type_name = types[reg]
        else:
            tnlen = _i32(seg, i); i += 4
            if not 1 <= tnlen <= MAX_TYPE_NAME or i + tnlen + 4 > len(seg):
                raise Sh2ParseError(f"битая длина имени типа {tnlen} @{i} (reg {reg})")
            type_name = seg[i:i + tnlen].decode("ascii", errors="replace")
            i += tnlen
            types[reg] = type_name
            # parent slot: reg-индекс предка. parent==своего reg, уже
            # зарегистрированный reg или 0 -> ссылки достаточно, payload сразу;
            # неизвестный parent -> читается его запись имени [len][name]; после
            # неё следующий dword снова слот предка ТОЛЬКО если похож на слот
            # (0/reg/продолжение цепочки), иначе это начало payload (S2Game:
            # payload часто стартует маркером A5C1FFFF — факт корпуса).
            depth = 0
            parent = _i32(seg, i); i += 4
            while (parent != reg and parent not in types and parent != 0
                   and depth < MAX_CHAIN_DEPTH):
                ptnlen = _i32(seg, i); i += 4
                if not 1 <= ptnlen <= MAX_TYPE_NAME or i + ptnlen + 4 > len(seg):
                    raise Sh2ParseError(f"битая длина имени предка {ptnlen} @{i}")
                ptn = seg[i:i + ptnlen].decode("ascii", errors="replace")
                i += ptnlen
                types[parent] = ptn
                chain.append((parent, ptn))
                if not _looks_like_parent_slot(seg, i, reg, types):
                    break  # payload начинается прямо здесь, слота больше нет
                parent = _i32(seg, i); i += 4
                depth += 1
        seen_ids.add(obj_id)
        if type_name == "HeightLayer":
            p = _heightlayer_payload_end(seg, i)
        else:
            p = seg.find(END_OBJ, i)
        if p < 0:
            raise Sh2ParseError(f"нет маркера конца объекта для id={obj_id:#x}/{type_name}")
        _harvest_inline_registrations(seg[i:p], types)
        header = seg[node_start:i]
        if magic_prefix:
            header = magic_prefix + header
            magic_prefix = b""
        nodes.append(ObjectNode(obj_id=obj_id, reg_index=reg, type_name=type_name,
                                chain=chain, header=header, payload=seg[i:p]))
        i = p + 4
    raise Sh2ParseError(f"сегмент не завершён END_SEG (дошли до {i}/{len(seg)})")


def reconstruct_segment(nodes: list[ObjectNode], tail: bytes = b"") -> bytes:
    return b"".join(n.reconstruct() for n in nodes) + END_SEG + tail
