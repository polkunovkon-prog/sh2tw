"""catalog_maps.py — машиночитаемый реестр карт-заготовок (S3.0, Приложение E).

Обход корпуса .s2m (maps_dir_game + maps_dir_user из project.ini), разбор каждого
файла доказанным стеком S2.1/S2.2/S2.4 (s2m_file → object_tree → map_header) и
запись ref/maps_catalog.csv. Строки только из реального разбора — никаких ручных
значений; карты, не прошедшие декод, уходят в failures (их обязан видеть человек).

Счётчики по сегменту mapheader (факт корпуса, проба 23.11.2026 на 70 картах:
Mission — 105 узлов, ScenarioEvent — 1060 узлов): n_mission_objs = узлов с
type_name == "Mission", n_scenario_events = узлов с type_name ==
"ScenarioEvent". Сценарные подзадачи (Quest-семейство) сюда НЕ входят — они
живут в Trigger/Action-узлах, их семантика ещё не разобрана (S2.4 raw).
"""
from __future__ import annotations

import csv
from pathlib import Path

from .formats.map_header import decode_mapheader_segment
from .formats.object_tree import parse_segment
from .formats.s2m_file import S2mFile, Sh2ParseError
from .paths import Paths, load_paths

# Колонки CSV (имена — английские, по карточке S3.0; порядок фиксирован).
COLUMNS = ["filename", "map_name", "map_type_name", "n_castle_markers",
           "n_village_markers", "n_mission_objs", "n_scenario_events",
           "file_size_bytes"]


def corpus_map_files(paths: Paths, maps_dir: Path | None = None) -> list[Path]:
    """Список .s2m корпуса: maps_dir (если задан) иначе game+user.

    Дедуп по имени файла (first wins: game раньше user); порядок сортировки
    по имени без учёта регистра — он же порядок строк каталога.
    """
    roots = [maps_dir] if maps_dir else [paths.maps_dir_game, paths.maps_dir_user]
    seen: set[str] = set()
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for f in sorted(root.rglob("*.s2m"), key=lambda p: p.name.lower()):
            if f.is_file() and f.name.lower() not in seen:
                seen.add(f.name.lower())
                files.append(f)
    return files


def display_map_name(raw_name: str) -> str:
    """Имя из MapHeader: по формату начинается с обратного слэша (S2.4)."""
    return raw_name[1:] if raw_name.startswith("\\") else raw_name


def catalog_row(path: Path) -> dict:
    """Строка реестра для одной .s2m. Sh2ParseError — если разбор не прошёл."""
    m = S2mFile.load(path)
    seg = next((s for s in m.segments if s.name == "mapheader"), None)
    if seg is None:
        raise Sh2ParseError(f"{path.name}: нет сегмента mapheader")
    nodes, _trailer = parse_segment(seg.decompressed)
    decoded = decode_mapheader_segment(nodes)
    hdr = decoded["header"]
    markers = decoded["estate_markers"]
    return {
        "filename": path.name,
        "map_name": display_map_name(hdr.name),
        "map_type_name": hdr.map_type_name,
        "n_castle_markers": sum(1 for mk in markers if mk.kind == 2),
        "n_village_markers": sum(1 for mk in markers if mk.kind == 1),
        "n_mission_objs": sum(1 for nd in nodes if nd.type_name == "Mission"),
        "n_scenario_events": sum(1 for nd in nodes if nd.type_name == "ScenarioEvent"),
        "file_size_bytes": path.stat().st_size,
    }


def build_catalog(paths: Paths, maps_dir: Path | None = None) -> tuple[list[dict], list[str]]:
    """Строит строки каталога + список провалов («file: exception» — блокеры)."""
    rows: list[dict] = []
    failures: list[str] = []
    for f in corpus_map_files(paths, maps_dir):
        try:
            rows.append(catalog_row(f))
        except Exception as e:  # протокол 00: не глотать молча — в failures и вывод
            failures.append(f"{f.name}: {type(e).__name__}: {e}")
    rows.sort(key=lambda r: r["filename"].lower())
    return rows, failures


def write_catalog_csv(rows: list[dict], out_path: Path) -> None:
    """Пишет CSV (UTF-8, CRLF — как ref/unit_types.csv), поверх целиком."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\r\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_catalog_maps(repo_root: Path, maps_dir: Path | None = None,
                     out: Path | None = None) -> dict:
    """Полный цикл CLI catalog-maps: обход → разбор → CSV; сводка для печати."""
    paths = load_paths()
    rows, failures = build_catalog(paths, maps_dir)
    out_path = out or (repo_root / "ref" / "maps_catalog.csv")
    write_catalog_csv(rows, out_path)
    return {"csv": str(out_path), "rows": len(rows), "failures": failures}
