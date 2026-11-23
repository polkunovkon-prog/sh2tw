"""Интеграционные тесты генератора (S3.8; приёмка 05 §5.9).

Собираются все 4 типа сцен (field/siege/defense/development) на шаблонах-
фикстурах → load парсером → валидации зелёные. Живая загрузка в игре —
V12 (человек), здесь машинная часть.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sh2tw.formats.map_header import decode_mapheader_segment
from sh2tw.formats.object_tree import parse_segment
from sh2tw.formats.s2m_file import S2mFile
from sh2tw.scenes.event_dsl import scene_events
from sh2tw.scenes.generator import (
    GeneratorError,
    build_scene,
    cleanup_generated,
)
from sh2tw.scenes.patcher import (
    Patch,
    PatchManifest,
    apply_patches,
    find_all,
)
from sh2tw.scenes.templates import (
    Template,
    add_repo_template,
    default_recommendations,
    load_registry,
    save_registry,
    template_for_role,
    TemplateError,
)

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"


def spec_for(scene_type: str, scene_id: str = "sc0101",
             archers: int = 20, spearmen: int = 30) -> dict:
    """Сбалансированный spec: лучник 30 з., копейщик 20 з. → 20×30 == 30×20."""
    return {
        "schema_version": "1.0",
        "scene_id": scene_id,
        "type": scene_type,
        "created_by": "shell",
        "region": "r01",
        "duration_months": 40,
        "sides": [
            {"role": "attacker", "lord": "player", "is_human": True,
             "provision": {"channel": "estate_troops",
                           "roster": {"archer": {"count": archers, "vet": 0.0}}}},
            {"role": "defender", "lord": "l_hawk", "is_human": False,
             "provision": {"channel": "aic_template",
                           "garrison_roster": {"spearman": {"count": spearmen,
                                                            "vet": 0.0}}}},
        ],
        "map_source": {"kind": "template", "template_id": "tpl_fixture"},
        "map_header_overrides": {
            "estate_markers": "inherit",
            "mission_events": scene_events(scene_type, [
                {"role": "attacker", "lord": "player", "is_human": True},
                {"role": "defender", "lord": "l_hawk", "is_human": False}], 40),
        },
        "honesty": {"snapshot_points": ["start", "end"], "enabled": True},
    }


@pytest.fixture()
def tpl() -> Template:
    return Template(template_id="tpl_fixture", kind="game_map",
                    file="", sha256=None, roles=["siege"])


class FixtureTemplate(Template):
    """Шаблон-фикстура: файл из tests/data напрямую."""

    def __init__(self, file: str):
        super().__init__(template_id="tpl_fixture", kind="game_map",
                         file=file, sha256=None, roles=["siege"])

    def resolve(self, game_maps_dir=None) -> Path:  # noqa: ANN001
        p = DATA / self.file
        if not p.exists():
            raise TemplateError(f"нет фикстуры {p}")
        return p


@pytest.mark.parametrize("scene_type", ["field", "siege", "defense", "development"])
def test_build_all_four_scene_types(tmp_path: Path, scene_type: str):
    spec = spec_for(scene_type)
    t = FixtureTemplate("sample.s2m")
    rep = build_scene(spec, t, tmp_path)
    # карта записана с правилом имени (03 §3.13)
    assert rep.map_path.name == f"S2TW_{spec['scene_id']}_{scene_type}.s2m"
    assert len(rep.map_path.name) <= 27 + 4
    assert rep.map_path.exists()
    # .build.json сателлит
    bj = json.loads(rep.build_json_path.read_text(encoding="utf-8"))
    assert bj["scene_id"] == spec["scene_id"]
    assert bj["template"]["template_id"] == "tpl_fixture"
    assert bj["checks"]["load_ok"] and bj["checks"]["roundtrip_stable"]
    # перечитали парсером — это валидный файл
    m = S2mFile.load(rep.map_path)
    assert m.roundtrip_ok()
    # mapheader: имя переписано, EstatesMarkers декодируются
    seg = next(s for s in m.segments if s.name == "mapheader")
    nodes, _ = parse_segment(seg.decompressed)
    dec = decode_mapheader_segment(nodes)
    assert dec["header"].name == rep.map_path.stem
    assert len(dec["estate_markers"]) == 32
    # RadarMap/S2Game не тронуты
    src = S2mFile.load(DATA / "sample.s2m")
    for name in ("radarmap", "s2game"):
        s_out = next(s for s in m.segments if s.name == name)
        s_src = next(s for s in src.segments if s.name == name)
        assert s_out.compressed == s_src.compressed


def test_build_scene_name_shortening(tmp_path: Path):
    spec = spec_for("siege", scene_id="sc_" + "x" * 40)
    rep = build_scene(spec, FixtureTemplate("sample.s2m"), tmp_path)
    assert len(rep.map_path.stem) <= 27  # 05 §5.10
    assert rep.map_path.exists()


def test_build_scene_rejects_imbalanced_provisioning(tmp_path: Path):
    spec = spec_for("siege", archers=40, spearmen=3)
    with pytest.raises(GeneratorError, match="provision_balance FAIL"):
        build_scene(spec, FixtureTemplate("sample.s2m"), tmp_path)


def test_build_scene_rejects_bad_spec(tmp_path: Path):
    spec = spec_for("siege")
    spec["type"] = "skirmish"
    with pytest.raises(GeneratorError, match="type"):
        build_scene(spec, FixtureTemplate("sample.s2m"), tmp_path)
    spec = spec_for("siege")
    spec["sides"] = [{"lord": "lonely"}]
    with pytest.raises(GeneratorError, match="≥2"):
        build_scene(spec, FixtureTemplate("sample.s2m"), tmp_path)
    spec = spec_for("siege")
    spec.pop("scene_id")
    with pytest.raises(GeneratorError, match="scene_id"):
        build_scene(spec, FixtureTemplate("sample.s2m"), tmp_path)


def test_build_scene_validates_mission_events(tmp_path: Path):
    spec = spec_for("siege")
    spec["map_header_overrides"]["mission_events"] = [
        {"after_months": 1, "action": "NotInList", "params": {}}]
    with pytest.raises(GeneratorError, match="mission_events"):
        build_scene(spec, FixtureTemplate("sample.s2m"), tmp_path)


def test_build_scene_with_patch_manifest(tmp_path: Path):
    """Полный цикл 05 §5.3: якорный патч применяется до писателя."""
    # разработка патча: уникальный якорь в payload EstateMarkers шаблона
    # (зона, которую писатель не пересобирает — правки имени не задеты)
    src = S2mFile.load(DATA / "sample.s2m")
    seg = next(s for s in src.segments if s.name == "mapheader")
    d = seg.decompressed
    nodes, _ = parse_segment(d)
    pos = 8  # magic-префикс
    em_range = None
    for n in nodes:
        end = pos + len(n.header) + len(n.payload) + 4
        if n.type_name == "EstateMarkers":
            em_range = (pos + len(n.header), pos + len(n.header) + len(n.payload))
            break
        pos = end
    assert em_range, "нет EstateMarkers в фикстуре"
    anchor_pos = -1
    for cand in range(em_range[0], em_range[1] - 12):
        window = d[cand:cand + 8]
        if window.count(b"\x00") >= 6:
            continue
        if len(find_all(d, window)) == 1:
            anchor_pos = cand
            break
    assert anchor_pos > 0
    anchor = d[anchor_pos:anchor_pos + 8]
    expected = d[anchor_pos + 8:anchor_pos + 12]
    new = bytes((b ^ 0x5A) for b in expected)
    man = PatchManifest(template_id="tpl_fixture", template_file="sample.s2m",
                        template_sha256=None,
                        patches=[Patch(id="probe_field", anchor=anchor,
                                       anchor_offset=0, expected=expected,
                                       new=new)])
    # патч применяется к сырому сегменту
    assert apply_patches(d, man) == d[:anchor_pos + 8] + new + d[anchor_pos + 12:]

    spec = spec_for("siege")
    rep = build_scene(spec, FixtureTemplate("sample.s2m"), tmp_path,
                      patch_manifest=man)
    # патченные байты доехали до собранной карты (писатель меняет длину
    # блока имени — проверяем паттерн «якорь+новое значение», не смещение)
    m = S2mFile.load(rep.map_path)
    out_seg = next(s for s in m.segments if s.name == "mapheader")
    assert anchor + new in out_seg.decompressed
    bj = json.loads(rep.build_json_path.read_text(encoding="utf-8"))
    assert bj["patch_manifest"] == "tpl_fixture"


def test_build_scene_estate_marker_overrides(tmp_path: Path):
    spec = spec_for("siege")
    spec["map_header_overrides"]["estate_markers"] = [{"slot": 0, "kind": 2}]
    rep = build_scene(spec, FixtureTemplate("sample.s2m"), tmp_path)
    m = S2mFile.load(rep.map_path)
    seg = next(s for s in m.segments if s.name == "mapheader")
    nodes, _ = parse_segment(seg.decompressed)
    dec = decode_mapheader_segment(nodes)
    assert dec["estate_markers"][0].kind == 2


def test_build_scene_deterministic(tmp_path: Path):
    """Два прогона — байт-идентичные карты (детерминизм, 04 §4.7)."""
    spec = spec_for("field")
    rep1 = build_scene(spec, FixtureTemplate("sample.s2m"), tmp_path / "a")
    rep2 = build_scene(spec, FixtureTemplate("sample.s2m"), tmp_path / "b")
    assert rep1.map_path.read_bytes() == rep2.map_path.read_bytes()


def test_generation_performance_under_30s(tmp_path: Path):
    """05 §5.9: генерация ≤30 с на карту."""
    import time
    t0 = time.monotonic()
    build_scene(spec_for("siege"), FixtureTemplate("sample.s2m"),
                tmp_path / "perf")
    assert time.monotonic() - t0 < 30.0


# ------------------------------------------------------------- templates
def test_default_recommendations_from_catalog():
    recs = default_recommendations()
    # каталог в репо отсутствует → пусто (честно); создаём временный
    import csv as _csv
    tmp = Path("/tmp") / "sh2tw_test_catalog"
    tmp.mkdir(parents=True, exist_ok=True)
    cat = tmp / "maps_catalog.csv"
    cat.write_text(
        "filename,map_type_name,n_castle_markers,n_village_markers,n_mission_objs,n_scenario_events,file_size_bytes\n"
        "Strong and Stable.s2m,kingmaker,8,6,1,1,1000\n"
        "Two Pronged Crown.s2m,kingmaker,6,4,1,1,1000\n"
        "war_chapter8.s2m,war_custom,5,6,3,76,2000\n"
        "Kill Barclay.s2m,war_custom,2,10,1,23,1500\n", encoding="utf-8")
    recs = default_recommendations(cat)
    assert recs["field"][0]["filename"] == "Strong and Stable.s2m"
    assert any(r["filename"] == "war_chapter8.s2m" for r in recs["siege"]) or \
           recs["siege"][0]["filename"] == "Kill Barclay.s2m"
    assert recs["theater"][0]["filename"] == "Strong and Stable.s2m"


def test_registry_roundtrip_and_role_lookup(tmp_path: Path):
    reg_path = tmp_path / "templates.json"
    t = add_repo_template("tpl_siege_a", DATA / "sample.s2m", ["siege"],
                          verify_sha=True)
    save_registry([t], reg_path)
    loaded = load_registry(reg_path)
    assert loaded[0].template_id == "tpl_siege_a"
    assert loaded[0].sha256 and loaded[0].roles == ["siege"]
    assert loaded[0].resolve() == (Path.cwd() / "templates/maps/sample.s2m") \
        or loaded[0].resolve().name == "sample.s2m"
    # cleanup зачисленных копий
    import shutil
    shutil.rmtree(Path.cwd() / "templates" / "maps", ignore_errors=True)


def test_template_for_role_fallback_game_map(tmp_path: Path, monkeypatch):
    import sh2tw.scenes.templates as T
    # нет реестра и нет каталога → TemplateError
    monkeypatch.setattr(T, "REGISTRY_PATH", tmp_path / "no_registry.json")
    monkeypatch.setattr(T, "CATALOG_CSV", tmp_path / "no_catalog.csv")
    with pytest.raises(TemplateError):
        template_for_role("siege", game_maps_dir=tmp_path)
    # с каталогом — game_map-рекомендация
    cat_dir = tmp_path / "ref"
    cat_dir.mkdir()
    (cat_dir / "maps_catalog.csv").write_text(
        "filename,map_type_name,n_castle_markers,n_village_markers,n_mission_objs,n_scenario_events,file_size_bytes\n"
        "Kill Barclay.s2m,war_custom,2,10,1,23,1500\n", encoding="utf-8")
    monkeypatch.setattr(T, "CATALOG_CSV", cat_dir / "maps_catalog.csv")
    t = template_for_role("siege", game_maps_dir=tmp_path)
    assert t.kind == "game_map" and t.file == "Kill Barclay.s2m"


def test_add_repo_template_rejects_bad_role(tmp_path: Path):
    with pytest.raises(TemplateError):
        add_repo_template("x", DATA / "sample.s2m", ["naval"])


# ---------------------------------------------------------- cleanup-maps
def test_cleanup_generated(tmp_path: Path):
    (tmp_path / "S2TW_sc0001_siege.s2m").write_bytes(b"1")
    (tmp_path / "S2TW_sc0001_siege.s2m.build.json").write_text("{}")
    (tmp_path / "vanilla_map.s2m").write_bytes(b"2")
    dry = cleanup_generated(tmp_path, dry_run=True)
    assert dry["count"] == 2 and not dry["to_remove"] or dry.get("to_remove")
    assert set(dry["to_remove"]) == {"S2TW_sc0001_siege.s2m",
                                     "S2TW_sc0001_siege.s2m.build.json"}
    real = cleanup_generated(tmp_path, dry_run=False)
    assert real["count"] == 2
    assert not (tmp_path / "S2TW_sc0001_siege.s2m").exists()
    assert (tmp_path / "vanilla_map.s2m").exists()  # ванилла не тронута
