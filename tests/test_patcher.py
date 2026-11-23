"""Тесты патчера L1 и diff-maps (S3.2; 03 §3.8, 05 §5.3/§5.9).

Юнит-приёмка 05 §5.9: якорь не найден / найден дважды / mismatch — все дают
исключения; равнодлинность — на этапе загрузки манифеста.
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path

import pytest

from sh2tw.formats.s2m_file import S2mFile
from sh2tw.scenes.diff_maps import diff_maps, diff_maps_json
from sh2tw.scenes.patcher import (
    Patch,
    PatchAnchorError,
    PatchError,
    PatchManifest,
    PatchManifestError,
    PatchMismatchError,
    apply_patches,
    diff_buffers,
    find_all,
    parse_hex,
)

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"


# ------------------------------------------------------------------ helpers
def manifest(patches: list[Patch], template_id: str = "tpl_test") -> PatchManifest:
    return PatchManifest(template_id=template_id, template_file="t.s2m",
                         template_sha256="0" * 64, patches=patches)


def patch(pid: str, anchor: bytes, off: int, expected: bytes, new: bytes) -> Patch:
    return Patch(id=pid, anchor=anchor, anchor_offset=off,
                 expected=expected, new=new)


# ------------------------------------------------------------------- parse_hex
def test_parse_hex_ok_and_rejects_garbage():
    assert parse_hex("E8 03 00 00") == b"\xe8\x03\x00\x00"
    assert parse_hex("e803") == b"\xe8\x03"
    with pytest.raises(PatchManifestError):
        parse_hex("нет")
    with pytest.raises(PatchManifestError):
        parse_hex("")


def test_find_all_finds_overlapping_too():
    buf = b"\x00" + b"AB" * 3 + b"\x00"
    # поиск с шагом +1: пересекающиеся вхождения тоже считаются — для
    # проверки уникальности якоря это строгий (безопасный) подсчёт
    assert find_all(buf, b"ABAB") == [1, 3]
    assert find_all(buf, b"ZZ") == []


# ------------------------------------------------------------ apply_patches
def test_apply_single_patch_happy_path():
    seg = b"PREFIX" + b"\x10\x27\x00\x00" + b"SUFFIX"
    man = manifest([patch("start_gold.lord0", b"PREFIX", 0,
                          b"\x10\x27\x00\x00", b"\xc0\x5d\x00\x00")])
    out = apply_patches(seg, man)
    assert out == b"PREFIX" + b"\xc0\x5d\x00\x00" + b"SUFFIX"
    assert len(out) == len(seg)  # равнодлинность


def test_apply_patches_in_order_multiple():
    seg = b"AAA\x01BBB\x02CCC"
    man = manifest([
        patch("p1", b"AAA", 0, b"\x01", b"\x05"),
        patch("p2", b"BBB", 0, b"\x02", b"\x06"),
    ])
    assert apply_patches(seg, man) == b"AAA\x05BBB\x06CCC"


def test_anchor_not_found_raises():
    man = manifest([patch("p", b"NOPE", 0, b"\x01", b"\x02")])
    with pytest.raises(PatchAnchorError):
        apply_patches(b"AAA\x01BBB", man)


def test_anchor_found_twice_raises():
    seg = b"KEY\x01XKEY\x01Y"
    man = manifest([patch("p", b"KEY", 0, b"\x01", b"\x02")])
    with pytest.raises(PatchAnchorError) as ei:
        apply_patches(seg, man)
    assert ei.value.occurrences == 2


def test_expected_mismatch_raises_with_context():
    seg = b"ANCHOR" + b"\xff\xff\xff\xff" + b"TAIL"
    man = manifest([patch("p", b"ANCHOR", 0,
                          b"\x10\x27\x00\x00", b"\xc0\x5d\x00\x00")])
    with pytest.raises(PatchMismatchError) as ei:
        apply_patches(seg, man)
    assert ei.value.found == b"\xff\xff\xff\xff"
    assert "context" in str(ei.value) or ei.value.expected == b"\x10\x27\x00\x00"


def test_anchor_offset_from_end_of_anchor():
    # смещение считается от КОНЦА якоря (03 §3.8): якорь ABCD, offset 2
    seg = b"ABCD" + b"\x00\x00" + b"\x99" + b"REST"
    man = manifest([patch("p", b"ABCD", 2, b"\x99", b"\x77")])
    assert apply_patches(seg, man) == b"ABCD\x00\x00\x77REST"


def test_patch_beyond_segment_end_raises():
    man = manifest([patch("p", b"AB", 100, b"\x01", b"\x02")])
    with pytest.raises(PatchMismatchError):
        apply_patches(b"AB", man)


# ---------------------------------------------------------------- манифест
def test_manifest_roundtrip_dict_and_rejects_unequal_lengths():
    man = manifest([patch("g0", b"\xe8\x03", 12, b"\x10\x27", b"\xc0\x5d")])
    d = man.as_dict()
    assert d["patches"][0]["anchor_hex"] == "E8 03"
    man2 = PatchManifest.from_dict(d)
    assert man2.as_dict() == d  # round-trip манифеста
    bad = {"schema_version": "1.0", "template_id": "t",
           "patches": [{"id": "x", "anchor_hex": "E8 03", "anchor_offset": 0,
                        "expected_hex": "10 27", "new_hex": "C0 5D 00"}]}
    with pytest.raises(PatchManifestError, match="равнодлинности"):
        PatchManifest.from_dict(bad)


def test_manifest_rejects_bad_schema_and_duplicate_ids():
    with pytest.raises(PatchManifestError):
        PatchManifest.from_dict({"schema_version": "9.9", "template_id": "t"})
    dup = {"schema_version": "1.0", "template_id": "t", "patches": [
        {"id": "x", "anchor_hex": "E8", "anchor_offset": 0,
         "expected_hex": "10", "new_hex": "C0"},
        {"id": "x", "anchor_hex": "E9", "anchor_offset": 0,
         "expected_hex": "10", "new_hex": "C0"}]}
    with pytest.raises(PatchManifestError, match="дубль"):
        PatchManifest.from_dict(dup)


def test_manifest_length_check_field_must_match():
    d = {"schema_version": "1.0", "template_id": "t", "patches": [
        {"id": "x", "anchor_hex": "E8 03", "anchor_offset": 0,
         "expected_hex": "10 27", "new_hex": "C0 5D", "length_check": 8}]}
    with pytest.raises(PatchManifestError, match="length_check"):
        PatchManifest.from_dict(d)


# ------------------------------------------------------------ diff_buffers
def test_diff_buffers_equal_length_finds_regions():
    a = b"AAAA" + b"\x01\x02" + b"BBBB"
    b = b"AAAA" + b"\x09\x02" + b"BBBB"
    diffs = diff_buffers(a, b)
    assert len(diffs) == 1
    d = diffs[0]
    assert d["offset"] == 4 and d["length"] == 1
    assert d["a_hex"] == "01" and d["b_hex"] == "09"
    assert "context_hex" in d


def test_diff_buffers_identical_is_empty():
    assert diff_buffers(b"xyz" * 10, b"xyz" * 10) == []


def test_diff_buffers_rejects_unequal_lengths():
    with pytest.raises(PatchError, match="равнодлинность"):
        diff_buffers(b"AAA", b"AAAA")


# ------------------------------------------------------------- diff_maps CLI
def test_diff_maps_identical_files():
    doc = diff_maps(DATA / "sample.s2m", DATA / "sample.s2m")
    assert doc["summary"]["identical"] is True
    assert doc["summary"]["total_diff_regions"] == 0


def test_diff_maps_detects_mapheader_change():
    """Правка сегмента mapheader у копии карты → diff-maps находит её."""
    src = S2mFile.load(DATA / "sample.s2m")
    seg = next(s for s in src.segments if s.name == "mapheader")
    d = bytearray(seg.decompressed)
    # процедура 05 §5.3: ищем уникальный 8-байтовый якорь (как разработчик
    # патча) и правим 4 байта ПОСЛЕ него — равнодлинная правка
    anchor_pos = -1
    for cand in range(64, len(d) - 12):
        window = bytes(d[cand:cand + 8])
        if window.count(b"\x00") >= 6:
            continue  # вырожденное окно из нулей — не годится как якорь
        if len(find_all(bytes(d), window)) == 1:
            anchor_pos = cand
            break
    assert anchor_pos > 0, "не нашли уникальный якорь в фикстуре"
    anchor = bytes(d[anchor_pos:anchor_pos + 8])
    expected = bytes(d[anchor_pos + 8:anchor_pos + 12])
    new = bytes((b ^ 0xFF) for b in expected)  # инверсия — равнодлинная правка
    d[anchor_pos + 8:anchor_pos + 12] = new
    patched = S2mFile(
        path=None, file_header=src.file_header,
        segments=[type(seg)(name=seg.name, decompressed=bytes(d),
                            compressed=zlib.compress(bytes(d), 6),
                            offset=seg.offset, level=6)
                  if s.name == "mapheader" else s
                  for s in src.segments],
        tail=src.tail)
    tmp = Path("/tmp") / "sh2tw_test_diff_maps"
    tmp.mkdir(parents=True, exist_ok=True)
    edited = tmp / "sample_edited.s2m"
    edited.write_bytes(patched.roundtrip_bytes())
    doc = diff_maps(DATA / "sample.s2m", edited)
    assert doc["summary"]["identical"] is False
    assert doc["segments"]["mapheader"]["diff_count"] == 1
    diffs = doc["segments"]["mapheader"]["diffs"]
    assert bytes.fromhex(diffs[0]["a_hex"].replace(" ", "")) == expected
    assert bytes.fromhex(diffs[0]["b_hex"].replace(" ", "")) == new
    # и патчер применяет правку по якорю — полный цикл разработки патча
    man = manifest([patch("probe", anchor, 0, expected, new)],
                   template_id="tpl_sample")
    assert apply_patches(seg.decompressed, man) == bytes(d)
    # заголовок и трейлер не тронуты
    assert doc["file_header"]["equal"] is True
    assert doc["tail"]["equal"] is True
    # детерминированный JSON
    assert diff_maps_json(doc) == diff_maps_json(diff_maps(DATA / "sample.s2m", edited))


def test_diff_maps_handles_different_segment_length():
    """Разная длина сегмента (правка L2-типа) — честная пометка, не краш."""
    src = S2mFile.load(DATA / "sample.s2m")
    seg = next(s for s in src.segments if s.name == "mapheader")
    d = seg.decompressed + b"\x00" * 8  # +8 байт = «добавлена запись»
    patched = S2mFile(
        path=None, file_header=src.file_header,
        segments=[type(seg)(name=seg.name, decompressed=bytes(d),
                            compressed=zlib.compress(bytes(d), 6),
                            offset=seg.offset, level=6)
                  if s.name == "mapheader" else s
                  for s in src.segments],
        tail=src.tail)
    tmp = Path("/tmp") / "sh2tw_test_diff_maps"
    tmp.mkdir(parents=True, exist_ok=True)
    edited = tmp / "sample_longer.s2m"
    edited.write_bytes(patched.roundtrip_bytes())
    doc = diff_maps(DATA / "sample.s2m", edited)
    sec = doc["segments"]["mapheader"]
    assert sec["length_equal"] is False and sec["length_delta"] == 8
    assert "L2" in sec["note"]


def test_manifest_json_load_from_file(tmp_path: Path):
    man = manifest([patch("g0", b"\xe8\x03", 12, b"\x10\x27", b"\xc0\x5d")])
    p = tmp_path / "tpl_test.patch.json"
    p.write_text(json.dumps(man.as_dict(), ensure_ascii=False, indent=1),
                 encoding="utf-8")
    loaded = PatchManifest.load(p)
    assert loaded.template_id == "tpl_test"
    assert loaded.patches[0].expected == b"\x10\x27"
    broken = tmp_path / "broken.patch.json"
    broken.write_text("{не json", encoding="utf-8")
    with pytest.raises(PatchManifestError):
        PatchManifest.load(broken)
