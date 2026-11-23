"""diff_maps.py — побайтовое сравнение двух карт/сейвов по сегментам (S3.2).

Основа процедуры разработки патчей (05 §5.3 п.3): копия шаблона правится в
редакторе игры → `diff-maps original.s2m edited.s2m` → изменённые байты с
контекстом ±16 по сегментам → выбор якоря → запись патча.

Разная длина распакованных сегментов НЕ ошибка сравнения: правки, меняющие
длину (строки, добавление записей), — территория писателя L2 (05 §5.3);
diff-maps честно показывает и их (дифф по общей длине + дельта длины).
"""
from __future__ import annotations

import json
from pathlib import Path

from ..formats.s2m_file import S2mFile, Sh2ParseError
from .patcher import PatchError, diff_buffers

SCHEMA_VERSION = "1.0"
CONTEXT = 16


def diff_maps(a_path: Path, b_path: Path) -> dict:
    """Документ различий двух .s2m/.sh2: заголовок, сегменты, трейлер."""
    a_path, b_path = Path(a_path), Path(b_path)
    ma = S2mFile.load(a_path)
    mb = S2mFile.load(b_path)

    def seg_by_name(m: S2mFile) -> dict[str, object]:
        return {s.name: s for s in m.segments}

    sa, sb = seg_by_name(ma), seg_by_name(mb)
    segments_out: dict[str, dict] = {}
    for name in sorted(set(sa) | set(sb)):
        if name not in sa or name not in sb:
            segments_out[name] = {"present": [name in sa, name in sb]}
            continue
        da, db = sa[name].decompressed, sb[name].decompressed  # type: ignore[attr-defined]
        if len(da) == len(db):
            diffs = diff_buffers(da, db, CONTEXT)
            segments_out[name] = {
                "length_equal": True, "length": len(da),
                "diff_count": len(diffs), "diffs": diffs}
        else:
            common = min(len(da), len(db))
            diffs = diff_buffers(da[:common], db[:common], CONTEXT)
            segments_out[name] = {
                "length_equal": False, "length_a": len(da), "length_b": len(db),
                "length_delta": len(db) - len(da),
                "note": "разная длина распакованного сегмента — правка меняет "
                        "длину (строки/записи): территория писателя L2 (05 §5.3)",
                "diff_count": len(diffs), "diffs": diffs}

    hdr_note = None
    hdr_diffs: list[dict] = []
    if ma.file_header.raw != mb.file_header.raw:
        common = min(len(ma.file_header.raw), len(mb.file_header.raw))
        if len(ma.file_header.raw) == len(mb.file_header.raw):
            hdr_diffs = diff_buffers(ma.file_header.raw, mb.file_header.raw, CONTEXT)
        else:
            hdr_diffs = diff_buffers(ma.file_header.raw[:common],
                                     mb.file_header.raw[:common], CONTEXT)
            hdr_note = (f"длина заголовка изменилась: {len(ma.file_header.raw)} → "
                        f"{len(mb.file_header.raw)} байт")
    tail_note = None
    if ma.tail != mb.tail:
        tail_note = (f"трейлер изменился: {len(ma.tail)} → {len(mb.tail)} байт "
                     f"(G14: переносится как есть)")

    n_diffs = sum(s.get("diff_count", 0) for s in segments_out.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "files": {"a": str(a_path), "b": str(b_path)},
        "file_header": {"equal": ma.file_header.raw == mb.file_header.raw,
                        "note": hdr_note, "diffs": hdr_diffs},
        "segments": segments_out,
        "tail": {"equal": ma.tail == mb.tail, "note": tail_note},
        "summary": {"segments_with_diffs": sum(
                        1 for s in segments_out.values() if s.get("diff_count")),
                    "total_diff_regions": n_diffs,
                    "identical": (ma.file_header.raw == mb.file_header.raw
                                  and n_diffs == 0 and ma.tail == mb.tail)},
    }


def diff_maps_json(doc: dict) -> str:
    """Канонический JSON (детерминированный)."""
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)


def run_diff_maps(a: Path, b: Path, out: Path | None = None) -> dict:
    """Точка входа CLI: сравнение + опциональная запись отчёта."""
    doc = diff_maps(a, b)
    if out is not None:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(diff_maps_json(doc) + "\n", encoding="utf-8")
    return doc
