"""diff_engine.py — механический diff двух snapshot'ов (S2.7, ТЗ 04 §4.2/§4.6).

Форма выдачи — стабильный машиночитаемый документ (детерминированный
canonical JSON: sort_keys, фиксированный indent, списки отсортированы по
ключу): added/removed/changed размещения по ключу obj_id с дельтами
класса (type_name) и позиции (x/z/y_raw); дельты census (плоские
dotted-ключи); дельты mapheader-секции map (когда присутствуют);
дельты container (file_header/segments — ASCII-заголовок карты из §4.3.1);
прямая выдача parse_errors обеих сторон.

Принципы честности (ТЗ 00 UNKNOWN, G18/S2.5/S2.6):
- диффуются ТОЛЬКО поля, которые snapshot реально несёт (см. build_snapshot);
  семантика игры НЕ выдумывается: никаких building_built/lord_died/battle —
  lords, population, owner_lord, hp_pct, game_time_months сейчас null
  (причины — unknown_fields), значит события §3.6 из snapshot выводиться
  не могут и не выводятся. Это осознанное расхождение с карманом events
  03 §3.6 — закрытие ждёт декодеровScenario/owner (блокер в реестре).
- UNKNOWN(null) vs null — НЕ изменение (None == None); None vs значение
  (например map не раскодан на одном файле) — фиксируется как смена
  доступности (map_available), а не как выдуманная дельта полей.
- obj_id читается из файла (object_tree), но между СЕЙВАМИ одного сцены-
  матча он не обязан означать «тот же объект» (замер V3 23.11.2026: у пары
  одного объекта при том же obj_id меняется type_name). Diff механический:
  changed-строка несёт дельту класса явно — интерпретация на потребителе
  (08/V3), движок ничего не «склеивает».

Детерминизм: тот же вход → байт-идентичный JSON (wall clock не пишется;
parsed_at берётся из source снимка, он сам mtime-детерминирован S2.6).
Дубликаты ключей (obj_id/marker_slot) в секции — честный откат на
multiset-diff по canonical JSON строки (changed при этом пуст).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .snapshot_builder import SCHEMA_VERSION as SNAP_SCHEMA
from .snapshot_builder import build_snapshot

DIFF_SCHEMA_VERSION = "1.0"

# Секции размещения: имя в снимке -> ключ строки-размещения.
_PLACEMENT_SECTIONS = {"buildings": "obj_id", "actors": "obj_id"}
_ESTATE_KEY = "marker_slot"


def diff_json(doc: dict) -> str:
    """Канонический JSON diff-документа (детерминированный, как snapshot_json)."""
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)


def load_snapshot(path: Path) -> dict:
    """Снимок из .json (уже собранный CLI parse) либо из .s2m/.sh2 встроенным
    парсером (build_snapshot) — одна точка входа для CLI diff (04 §4.6)."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        snap = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(snap, dict) or "census" not in snap or "schema_version" not in snap:
            raise ValueError(f"{path.name}: JSON есть, но это не snapshot (нет census/schema_version)")
        return snap
    return build_snapshot(path)


def _meta(snap: dict) -> dict:
    src = snap.get("source") or {}
    return {"file": src.get("file"), "name": src.get("name"),
            "sha256": src.get("sha256"),
            "snapshot_schema": snap.get("schema_version"),
            "map_name": (snap.get("map") or {}).get("name")}


def _index_rows(rows: list[dict], key: str) -> tuple[dict, bool]:
    """rows -> {ключ: строка}; второй флаг — были ли дубликаты ключей."""
    out: dict = {}
    dups = False
    for r in rows:
        k = r.get(key)
        if k in out:
            dups = True
        out.setdefault(k, r)
    return out, dups


def _sort_key_rows(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: diff_json(r))


def _diff_rows(rows_a: list[dict], rows_b: list[dict], key: str) -> dict:
    ia, dup_a = _index_rows(rows_a, key)
    ib, dup_b = _index_rows(rows_b, key)
    if dup_a or dup_b:
        # нечестный ключ (дубликаты) — multiset по строке целиком, changed не выдумываем
        ca = Counter(diff_json(r) for r in rows_a)
        cb = Counter(diff_json(r) for r in rows_b)
        added = _sort_key_rows([json.loads(s) for s in (cb - ca).elements()])
        removed = _sort_key_rows([json.loads(s) for s in (ca - cb).elements()])
        return {"keyed_by": f"row-json (дубликаты {key})",
                "added": added, "removed": removed, "changed": [],
                "unchanged": sum((ca & cb).values()),
                "summary": {"added": len(added), "removed": len(removed),
                            "changed": 0,
                            "unchanged": sum((ca & cb).values())}}
    added = [ib[k] for k in sorted(set(ib) - set(ia), key=lambda k: (k is None, k))]
    removed = [ia[k] for k in sorted(set(ia) - set(ib), key=lambda k: (k is None, k))]
    changed: list[dict] = []
    unchanged = 0
    for k in sorted(set(ia) & set(ib), key=lambda k: (k is None, k)):
        ra, rb = ia[k], ib[k]
        if ra == rb:
            unchanged += 1
            continue
        deltas = {f: {"from": ra.get(f), "to": rb.get(f)}
                  for f in sorted(set(ra) | set(rb)) if ra.get(f) != rb.get(f)}
        if deltas:
            changed.append({key: k, "class_from": ra.get("type_name"),
                            "class_to": rb.get("type_name"), "deltas": deltas})
        else:  # UNKNOWN(null) vs null по всем полям — изменений нет
            unchanged += 1
    return {"keyed_by": key, "added": added, "removed": removed, "changed": changed,
            "unchanged": unchanged,
            "summary": {"added": len(added), "removed": len(removed),
                        "changed": len(changed), "unchanged": unchanged}}


def _flat_deltas(a, b, prefix: str = "", out: dict | None = None) -> dict:
    """Плоские дельты {dotted-ключ: {from,to}} для вложенных dict и списков
    dict с уникальным 'name' (segments). Неравные scalars/списки — лист."""
    if out is None:
        out = {}
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            _flat_deltas(a.get(k), b.get(k), f"{prefix}{k}.", out)
        return out
    if isinstance(a, list) and isinstance(b, list):
        na = [x for x in a if isinstance(x, dict) and isinstance(x.get("name"), str)]
        nb = [x for x in b if isinstance(x, dict) and isinstance(x.get("name"), str)]
        if len(na) == len(a) and len(nb) == len(b):
            ka = {x["name"] for x in na}
            kb = {x["name"] for x in nb}
            if len(ka) == len(a) and len(kb) == len(b):
                da = {x["name"]: x for x in na}
                db = {x["name"]: x for x in nb}
                for k in sorted(ka | kb):
                    _flat_deltas(da.get(k), db.get(k), f"{prefix}{k}.", out)
                return out
    if a != b:
        key = prefix[:-1] if prefix.endswith(".") else prefix
        out[key] = {"from": a, "to": b}
    return out


def _map_deltas(sa: dict, sb: dict) -> dict:
    ma, mb = sa.get("map"), sb.get("map")
    if ma is None and mb is None:
        return {}
    if ma is None or mb is None:
        # mapheader на одной стороне не раскодан (parse_errors) — фиксируем
        # доступность, дельты полей не выдумываем
        return {"map_available": {"from": ma is not None, "to": mb is not None}}
    return _flat_deltas(ma, mb)


def _delta_months(sa: dict, sb: dict) -> int | None:
    ta, tb = sa.get("game_time_months"), sb.get("game_time_months")
    if ta is None or tb is None:
        return None
    return tb - ta


def diff_dicts(sa: dict, sb: dict) -> dict:
    """Ядро: два snapshot-dict -> diff-документ (без I/O)."""
    placements = {sec: _diff_rows(sa.get(sec) or [], sb.get(sec) or [], key)
                  for sec, key in _PLACEMENT_SECTIONS.items()}
    estates = _diff_rows(sa.get("estates") or [], sb.get("estates") or [], _ESTATE_KEY)
    census_deltas = _flat_deltas(sa.get("census") or {}, sb.get("census") or {})
    map_deltas = _map_deltas(sa, sb)
    container_deltas = _flat_deltas(sa.get("container") or {}, sb.get("container") or {})
    pe_a = list(sa.get("parse_errors") or [])
    pe_b = list(sb.get("parse_errors") or [])
    doc = {
        "schema_version": DIFF_SCHEMA_VERSION,
        "from": _meta(sa),
        "to": _meta(sb),
        "delta_months": _delta_months(sa, sb),
        "placements": placements,
        "estates": estates,
        "census_deltas": {k: census_deltas[k] for k in sorted(census_deltas)},
        "map_deltas": {k: map_deltas[k] for k in sorted(map_deltas)},
        "container_deltas": {k: container_deltas[k] for k in sorted(container_deltas)},
        "parse_errors": {"from": pe_a, "to": pe_b},
        "summary": {
            **{sec: placements[sec]["summary"] for sec in placements},
            "estates": estates["summary"],
            "census_delta_fields": len(census_deltas),
            "map_delta_fields": len(map_deltas),
            "container_delta_fields": len(container_deltas),
            "parse_errors_from": len(pe_a),
            "parse_errors_to": len(pe_b),
            "empty": (
                not any(placements[sec]["summary"]["added"] or
                        placements[sec]["summary"]["removed"] or
                        placements[sec]["summary"]["changed"] for sec in placements)
                and not estates["summary"]["added"] and not estates["summary"]["removed"]
                and not estates["summary"]["changed"]
                and not census_deltas and not map_deltas and not container_deltas
                and not pe_a and not pe_b),
        },
    }
    return doc


def diff_snapshots(a: Path, b: Path, out: Path | None = None) -> dict:
    """Сигнатура 04 §4.2 (diff_snapshots(a, b, out)). Возвращает diff-документ;
    out — canonical JSON туда (каталоги создаются). list[Event] из §4.2 —
    семантические события невыводимы из текущего снимка (см. шапку модуля).
    """
    doc = diff_dicts(load_snapshot(Path(a)), load_snapshot(Path(b)))
    if out is not None:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(diff_json(doc) + "\n", encoding="utf-8")
    return doc
