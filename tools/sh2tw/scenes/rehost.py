"""rehost.py — база карты из сейва (S3.6, L3; ТЗ 05 §5.6).

Механика: сейв сцены развития (контейнер тот же — F1/F12) → копия байтов →
писатель L2 переписывает ТОЛЬКО mapheader-сегмент (имя S2TW_*, тип карты,
EstateMarkers при необходимости); RadarMap и S2Game с реальной застройкой
игрока переносятся байт-в-байт (граница 02 §2.5).

Гейт V4 (F12: «сейв → карта» — гипотеза, живой эксперимент): до его
подтверждения rehost ОТКЛЮЧЕН по умолчанию (enabled=False в campaign_config
или конфиге проекта). Fallback при провале V4 — шаблоны уровней застройки
(05 §5.6), т.е. сцена обороны собирается генератором на обычном шаблоне.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path

from ..formats.object_tree import parse_segment
from ..formats.s2m_file import S2mFile, Sh2ParseError
from .mapheader_writer import MapHeaderWriter, WriterError


class RehostError(Exception):
    """Rehost недоступен/невозможен (гейт V4, битый сейв)."""


@dataclass
class RehostResult:
    data: bytes
    name: str
    source_save: str
    map_type: int


def rehost_save(save_path: Path, scene_name: str, map_type: int = 2,
                enabled: bool = False) -> RehostResult:
    """Сейв → байты карты-заготовки (S2TW_<scene_name>), гейт V4.

    enabled=False (по умолчанию — до закрытия V4) → RehostError: система
    обязана работать без rehost (02 §2.1, fallback — шаблоны уровней).
    """
    if not enabled:
        raise RehostError(
            "rehost отключён: гейт V4 не закрыт (F12: сейв→карта — гипотеза; "
            "эксперимент 10 §V4). Включение — после подтверждения человеком; "
            "fallback — шаблоны уровней застройки (05 §5.6)")
    save_path = Path(save_path)
    if save_path.suffix.lower() != ".sh2":
        raise RehostError(f"{save_path.name}: нужен сейв .sh2, не "
                          f"{save_path.suffix!r}")
    m = S2mFile.load(save_path)
    seg_mh = next((s for s in m.segments if s.name == "mapheader"), None)
    if seg_mh is None:
        raise Sh2ParseError(f"{save_path.name}: нет mapheader-сегмента")
    nodes, _tail = parse_segment(seg_mh.decompressed)
    try:
        writer = MapHeaderWriter(nodes)
        writer.set_name(scene_name)
        writer.set_map_type(map_type)
    except WriterError as e:
        raise RehostError(f"писатель L2: {e}") from e
    rebuilt = writer.to_segment()
    level = seg_mh.find_compression_level() or 6
    new_segments = [type(seg_mh)(name=seg_mh.name, decompressed=rebuilt,
                                 compressed=zlib.compress(rebuilt, level),
                                 offset=seg_mh.offset, level=level)
                    if s.name == "mapheader" else s
                    for s in m.segments]
    out = S2mFile(path=None, file_header=m.file_header,
                  segments=new_segments, tail=m.tail)
    return RehostResult(data=out.roundtrip_bytes(), name=scene_name,
                        source_save=str(save_path), map_type=map_type)


def build_defense_scene_from_snapshot(rehost: RehostResult) -> bytes:
    """Оборонительная сцена из rehost-базы: сейчас база уже несёт застройку;
    события/войска накладываются генератором (generator.py) поверх — здесь
    только передача байтов (единая точка API, 05 §5.6)."""
    return rehost.data
