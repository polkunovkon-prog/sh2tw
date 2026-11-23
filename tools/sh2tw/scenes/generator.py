"""generator.py — конвейер генерации сцены: scene_spec → карта (S3.8; 05 §5.2).

Шаги (ТЗ 05 §5.2):
  1. валидация spec + provision_balance (генератор ОБЯЗАН вызывать до записи);
  2. база: шаблон (template) или rehost-снимок (гейт V4);
  3. mapheader: патчи L1 (манифест) → писатель L2 (имя S2TW_*, тип, маркеры);
  4. mission_events → IR (валидация DSL; байты — через патч-манифесты, G18);
  5. сборка контейнера (RadarMap/S2Game — исходные сжатые байты, 02 §2.5);
  6. контр-проверки: load() без ошибок; round-trip собранного файла == себе
     (детерминизм сериализатора, 05 §5.5); provision pass;
  7. атомарная запись Maps/S2TW_<scene_id>_<type>.s2m + сателлит
     .build.json (что и откуда собрано) — имя ≤27 символов (05 §5.10).
"""
from __future__ import annotations

import json
import os
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from ..formats.object_tree import parse_segment
from ..formats.s2m_file import S2mFile, Sh2ParseError
from ..honesty.accounting import (HonestyError, load_unit_values,
                                  provision_balance_detail)
from .event_dsl import EventDslError, compile_events
from .mapheader_writer import MapHeaderWriter, WriterError
from .patcher import PatchManifest, apply_patches
from .templates import Template, TemplateError

SCHEMA_VERSION = "1.0"
SCENE_TYPES = ("field", "siege", "defense", "development")
MAP_TYPE_FOR_SCENE = {"field": 2, "siege": 2, "defense": 2}  # war_custom
NAME_MAX = 27  # 05 §5.10


class GeneratorError(Exception):
    """Генерация невозможна: описание в сообщении."""


@dataclass
class BuildReport:
    scene_id: str
    scene_type: str
    map_path: Path
    build_json_path: Path
    template_id: str
    template_sha256: str | None
    checks: dict = field(default_factory=dict)
    events_ir: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"scene_id": self.scene_id, "type": self.scene_type,
                "map": str(self.map_path),
                "build_json": str(self.build_json_path),
                "template_id": self.template_id,
                "template_sha256": self.template_sha256,
                "checks": self.checks, "events_ir": self.events_ir,
                "warnings": self.warnings}


def _validate_spec(spec: dict) -> None:
    if not isinstance(spec, dict):
        raise GeneratorError("scene_spec: объект JSON (03 §3.3)")
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise GeneratorError(f"schema_version {spec.get('schema_version')!r} "
                             f"!= {SCHEMA_VERSION!r}")
    sid = spec.get("scene_id")
    if not isinstance(sid, str) or not sid:
        raise GeneratorError("scene_id обязателен")
    if spec.get("type") not in SCENE_TYPES:
        raise GeneratorError(f"type {spec.get('type')!r} ∉ {SCENE_TYPES} (03 §3.3)")
    sides = spec.get("sides")
    if not isinstance(sides, list) or len(sides) < 2:
        raise GeneratorError("sides: ≥2 стороны (03 §3.3)")
    for s in sides:
        if not s.get("lord"):
            raise GeneratorError(f"side без lord: {s}")
        prov = s.get("provision") or {}
        if prov.get("channel") not in (None, "estate_troops", "invasion",
                                       "war_chest", "aic_template"):
            raise GeneratorError(f"side {s.get('lord')}: канал провижининга "
                                 f"{prov.get('channel')!r} неизвестен (02 §2.4)")


def _scene_map_name(spec: dict) -> str:
    name = f"S2TW_{spec['scene_id']}_{spec['type']}"
    if len(name) > NAME_MAX:
        # укорачиваем scene_id, сохраняя уникальность префиксом
        room = NAME_MAX - len(f"S2TW__{spec['type']}")
        name = f"S2TW_{spec['scene_id'][:room]}_{spec['type']}"
    return name


def build_scene(spec: dict, template: Template,
                out_dir: Path, game_maps_dir: Path | None = None,
                patch_manifest: PatchManifest | None = None,
                unit_values: dict | None = None) -> BuildReport:
    """scene_spec + шаблон → карта S2TW_<id>_<type>.s2m + .build.json."""
    _validate_spec(spec)
    try:
        balance = provision_balance_detail(spec, unit_values)
    except HonestyError as e:
        raise GeneratorError(f"provision_balance: {e}") from e
    if not balance.ok:
        raise GeneratorError(
            f"provision_balance FAIL (05 §5.2, до записи): {balance.detail} — "
            f"стороны: {balance.sides}; провижининг обязан быть ±10 % (03 §3.9)")

    tpl_path = template.resolve(game_maps_dir)
    try:
        src = S2mFile.load(tpl_path)
    except Sh2ParseError as e:
        raise GeneratorError(f"шаблон {template.template_id}: {e}") from e
    seg_mh = next((s for s in src.segments if s.name == "mapheader"), None)
    if seg_mh is None:
        raise GeneratorError("шаблон без mapheader-сегмента")

    # --- mapheader: L1 патчи → L2 писатель ---
    decompressed = seg_mh.decompressed
    if patch_manifest is not None:
        try:
            decompressed = apply_patches(decompressed, patch_manifest)
        except Exception as e:  # PatchAnchorError/PatchMismatchError
            raise GeneratorError(f"патч-манифест {patch_manifest.template_id}: "
                                 f"{e}") from e
    try:
        nodes, _tail = parse_segment(decompressed)
        writer = MapHeaderWriter(nodes)
        map_name = _scene_map_name(spec)
        writer.set_name(map_name)
        overrides = spec.get("map_header_overrides") or {}
        want_type = overrides.get("map_type")
        if want_type is None:
            want_type = MAP_TYPE_FOR_SCENE.get(spec["type"], writer.map_type)
        writer.set_map_type(want_type)
        markers = overrides.get("estate_markers") or []
        if markers == "inherit":
            markers = []
        if not isinstance(markers, list):
            raise GeneratorError("map_header_overrides.estate_markers: "
                                 "'inherit' либо список правок слотов")
        for m in markers:
            writer.set_estate_marker(**m)
        rebuilt = writer.to_segment()
    except (WriterError, Sh2ParseError) as e:
        raise GeneratorError(f"писатель L2: {e}") from e

    # --- mission_events → IR (байты — патч-манифесты, G18) ---
    events_ir: dict = {}
    warnings: list[str] = []
    me = (spec.get("map_header_overrides") or {}).get("mission_events")
    if me:
        try:
            prog = compile_events(me)
            events_ir = prog.summary()
        except EventDslError as e:
            raise GeneratorError(f"mission_events: {e}") from e
        warnings.append(
            "mission_events валидны и скомпилированы в IR; байтовая запись "
            "ScenarioEvent — через патч-манифесты шаблона (G18: формат "
            "не совпадает с докой OpenSH2, hexdiff-процедура 05 §5.3/V9)")

    # --- сборка контейнера (RadarMap/S2Game — исходные сжатые байты) ---
    level = seg_mh.find_compression_level() or 6
    new_mh = type(seg_mh)(name="mapheader", decompressed=rebuilt,
                          compressed=zlib.compress(rebuilt, level),
                          offset=seg_mh.offset, level=level)
    out_file = S2mFile(path=None, file_header=src.file_header,
                       segments=[new_mh if s.name == "mapheader" else s
                                 for s in src.segments],
                       tail=src.tail)

    # --- контр-проверки (05 §5.5) ---
    data = out_file.roundtrip_bytes()
    try:
        reloaded = S2mFile.loads(data)
    except Sh2ParseError as e:
        raise GeneratorError(f"собранная карта не читается парсером: {e}") from e
    checks = {
        "load_ok": True,
        "roundtrip_stable": reloaded.roundtrip_bytes() == data,
        "name": map_name,
        "provision_balance": balance.as_dict(),
    }
    if not checks["roundtrip_stable"]:
        raise GeneratorError("round-trip собранной карты не стабилен (05 §5.5)")

    # --- атомарная запись карты + сателлита ---
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    map_path = out_dir / f"{map_name}.s2m"
    _atomic_write(map_path, data)
    build_json = {
        "schema_version": SCHEMA_VERSION,
        "scene_id": spec["scene_id"],
        "type": spec["type"],
        "map": map_path.name,
        "template": {"template_id": template.template_id, "kind": template.kind,
                     "file": template.file,
                     "sha256": template.sha256,
                     "resolved_path": str(tpl_path)},
        "modifications": writer.build.modifications,
        "patch_manifest": patch_manifest.template_id if patch_manifest else None,
        "events_ir": events_ir,
        "checks": checks,
        "warnings": warnings,
        "spec": spec,
    }
    bj_path = map_path.with_suffix(".s2m.build.json")
    _atomic_write(bj_path, (json.dumps(build_json, ensure_ascii=False,
                                       indent=2, sort_keys=True) + "\n")
                  .encode("utf-8"))
    return BuildReport(scene_id=spec["scene_id"], scene_type=spec["type"],
                       map_path=map_path, build_json_path=bj_path,
                       template_id=template.template_id,
                       template_sha256=template.sha256,
                       checks=checks, events_ir=events_ir, warnings=warnings)


def _atomic_write(path: Path, data: bytes) -> None:
    """Запись tmp+rename — атомарность (R12, 06 §6.4)."""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def cleanup_generated(maps_dir: Path, dry_run: bool = True) -> dict:
    """Удаление сгенерированных S2TW_* карт (03 §3.13, CLI cleanup-maps)."""
    maps_dir = Path(maps_dir)
    removed: list[str] = []
    kept: list[str] = []
    for p in sorted(maps_dir.glob("S2TW_*")):
        if p.suffix.lower() in (".s2m", ".json"):
            if dry_run:
                kept.append(p.name)
            else:
                p.unlink()
                removed.append(p.name)
    return {"maps_dir": str(maps_dir), "dry_run": dry_run,
            "to_remove" if dry_run else "removed": kept if dry_run else removed,
            "count": len(kept if dry_run else removed)}
