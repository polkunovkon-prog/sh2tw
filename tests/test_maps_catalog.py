"""S3.0: машиночитаемый каталог карт-заготовок ref/maps_catalog.csv."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from sh2tw.catalog_maps import COLUMNS, corpus_map_files
from sh2tw.paths import load_paths

REPO = Path(__file__).resolve().parents[1]
CSV_PATH = REPO / "ref" / "maps_catalog.csv"


def _corpus_present() -> bool:
    p = load_paths()
    return any(d.exists() and list(d.rglob("*.s2m"))
               for d in (p.maps_dir_game, p.maps_dir_user))


def _rows() -> list[dict[str, str]]:
    if not CSV_PATH.exists():
        if not _corpus_present():
            pytest.skip("нет карт корпуса и нет CSV — генерация здесь невозможна")
        pytest.fail("ref/maps_catalog.csv нет — сгенерировать: "
                    "PYTHONPATH=tools python3 -m sh2tw.cli catalog-maps")
    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_csv_header_and_existence():
    rows = _rows()
    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == COLUMNS
    assert rows


def test_row_count_equals_corpus():
    n_corpus = len(corpus_map_files(load_paths()))
    if n_corpus == 0:
        pytest.skip("нет карт корпуса")
    assert len(_rows()) == n_corpus


def test_required_fields_nonempty():
    for r in _rows():
        assert r["filename"], f"пустой filename в {r}"
        assert r["map_type_name"] in ("kingmaker", "war_custom",
                                      "peace_custom", "free_build"), r
        for col in ("n_castle_markers", "n_village_markers",
                    "n_mission_objs", "n_scenario_events", "file_size_bytes"):
            assert int(r[col]) >= 0, (r["filename"], col)


def test_war_campaign_maps_have_castle_markers():
    by_name = {r["filename"].lower(): r for r in _rows()}
    checked = 0
    for name in ("war_chapter1.s2m", "war_chapter8.s2m"):
        if name not in by_name:
            pytest.skip(f"{name} нет в корпусе")
        assert int(by_name[name]["n_castle_markers"]) >= 1, by_name[name]
        checked += 1
    assert checked == 2
