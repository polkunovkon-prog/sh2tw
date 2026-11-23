"""Тесты rehost + раннера (S3.6/S3.7; ТЗ 05 §5.6/§5.7)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sh2tw.formats.object_tree import parse_segment
from sh2tw.formats.s2m_file import S2mFile
from sh2tw.scenes.rehost import RehostError, build_defense_scene_from_snapshot, rehost_save
from sh2tw.runner.launcher import LauncherError, launch, plan_launch
from sh2tw.runner.outcome import (
    OutcomeVerdict,
    build_scene_result,
    detect_outcome,
    manual_outcome,
    read_bridge_outcome,
    resolve_outcome,
)
from sh2tw.runner.saves_watcher import newest_save, scan_saves, wait_for_final_save
from sh2tw.runner.watchdog import MEM_LIMIT_MB, check_process, watchdog_report

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"


# ------------------------------------------------------------------ rehost
def test_rehost_disabled_by_default_until_v4():
    with pytest.raises(RehostError, match="V4"):
        rehost_save(DATA / "sample_save.sh2", "S2TW_sc0001_defense")


def test_rehost_enabled_rewrites_mapheader_keeps_s2game():
    res = rehost_save(DATA / "sample_save.sh2", "S2TW_sc0001_defense",
                      map_type=2, enabled=True)
    m = S2mFile.loads(res.data)
    # имя и тип переписаны
    seg = next(s for s in m.segments if s.name == "mapheader")
    nodes, _ = parse_segment(seg.decompressed)
    hdr = next(n for n in nodes if n.type_name == "MapHeader")
    n_chars = int.from_bytes(hdr.payload[32:36], "little")
    name = hdr.payload[36:36 + 2 * n_chars].decode("utf-16-le")
    assert name == "S2TW_sc0001_defense"
    # S2Game перенесён байт-в-байт (граница 02 §2.5)
    src = S2mFile.load(DATA / "sample_save.sh2")
    src_game = next(s for s in src.segments if s.name == "s2game")
    out_game = next(s for s in m.segments if s.name == "s2game")
    assert out_game.decompressed == src_game.decompressed
    # и весь файл перечитывается
    assert S2mFile.loads(m.roundtrip_bytes()).roundtrip_ok()
    # API оборонительной сцены
    assert build_defense_scene_from_snapshot(res) == res.data


def test_rehost_rejects_non_save():
    with pytest.raises(RehostError):
        rehost_save(DATA / "sample.s2m", "S2TW_x", enabled=True)


def test_rehost_rejects_bad_scene_name():
    with pytest.raises(RehostError):
        rehost_save(DATA / "sample_save.sh2", "no_prefix", enabled=True)


# ---------------------------------------------------------------- launcher
def test_plan_launch_instruction_without_exe(tmp_path: Path):
    map_path = tmp_path / "S2TW_sc0001_siege.s2m"
    map_path.write_bytes(b"x")
    plan = plan_launch(map_path, None)
    assert plan.mode == "instruction"
    assert "S2TW_sc0001_siege.s2m" in plan.instruction


def test_plan_launch_rejects_missing_map():
    with pytest.raises(LauncherError):
        plan_launch(Path("/tmp/sh2tw_nope.s2m"), None)


def test_plan_launch_rejects_non_s2tw_name(tmp_path: Path):
    p = tmp_path / "plain_map.s2m"
    p.write_bytes(b"x")
    with pytest.raises(LauncherError, match="S2TW_"):
        plan_launch(p, None)


def test_launch_dry_run_never_starts_process(tmp_path: Path):
    exe = tmp_path / "Stronghold2.exe"
    exe.write_bytes(b"MZ")
    map_path = tmp_path / "S2TW_sc0001_siege.s2m"
    map_path.write_bytes(b"x")
    res = launch(map_path, exe, dry_run=True)
    assert res["launched"] is False and res["plan"]["mode"] == "exe"


def test_launch_exe_mode_starts_and_watchdog_sees_it(tmp_path: Path):
    exe = tmp_path / "fake_game.exe" if sys.platform != "win32" \
        else tmp_path / "fake_game.bat"
    if sys.platform != "win32":
        exe.write_text("#!/bin/sh\nsleep 30\n")
        exe.chmod(0o755)
    else:
        exe.write_text("@echo off\r\nping -n 30 127.0.0.1 > nul\r\n")
    map_path = tmp_path / "S2TW_sc0001_siege.s2m"
    map_path.write_bytes(b"x")
    plan = plan_launch(map_path, exe)
    res = launch(map_path, exe, dry_run=False)
    assert res["launched"] is True and "pid" in res
    proc = subprocess.Popen([str(exe)])  # отдельный процесс для watchdog
    try:
        st = check_process(proc)
        assert st.running is True
    finally:
        proc.kill()
        proc.wait()
    st = check_process(proc)
    assert st.running is False


# ------------------------------------------------------------ saves_watcher
def test_scan_saves_finds_newer_than_start(tmp_path: Path):
    old = tmp_path / "old.sh2"
    old.write_bytes(b"1")
    time.sleep(0.02)
    since = time.time()
    time.sleep(0.02)
    new = tmp_path / "new.sh2"
    new.write_bytes(b"2")
    sub = tmp_path / "Restarts"
    sub.mkdir()
    sub_file = sub / "new_restart.sh2"
    sub_file.write_bytes(b"3")
    import os
    os.utime(sub_file, (since + 1, since + 1))
    cands = scan_saves(tmp_path, since)
    names = [c.path.name for c in cands]
    assert "new.sh2" in names and "new_restart.sh2" in names
    assert "old.sh2" not in names
    assert newest_save(tmp_path, since).path.name in ("new.sh2", "new_restart.sh2")
    assert newest_save(tmp_path, time.time() + 100) is None


def test_wait_for_final_save_timeout(tmp_path: Path):
    # нет сейвов + тайм-аут 0.3с → None
    assert wait_for_final_save(tmp_path, time.time(), True,
                               stable_secs=0.0, poll_interval=0.05,
                               timeout_secs=0.3) is None


# ----------------------------------------------------------------- outcome
def snap(lords, estates=None):
    return {"schema_version": "1.0", "source": {"file": "x"}, "map": {},
            "lords": lords, "estates": estates or [],
            "buildings": [], "actors": [], "census": {}}


def war_spec():
    return {"schema_version": "1.0", "scene_id": "sc_0009", "type": "siege",
            "duration_months": 40,
            "sides": [
                {"role": "attacker", "lord": "player", "is_human": True,
                 "lord_snapshot_index": 0,
                 "provision": {"channel": "estate_troops", "roster": {}}},
                {"role": "defender", "lord": "l_hawk", "is_human": False,
                 "lord_snapshot_index": 1,
                 "provision": {"channel": "aic_template", "garrison_roster": {}}},
            ]}


def test_detect_outcome_win_by_lord_death():
    start = snap([{"index": 0, "name": "player", "alive": True,
                   "gold": 0, "troops": {"archer": 20}},
                  {"index": 1, "name": "l_hawk", "alive": True,
                   "gold": 0, "troops": {"spearman": 22}}])
    end = snap([{"index": 0, "name": "player", "alive": True,
                 "gold": 0, "troops": {"archer": 14}},
                {"index": 1, "name": "l_hawk", "alive": False,
                 "gold": 0, "troops": {}}])
    v = detect_outcome(start, end, war_spec())
    assert v.outcome == "win" and v.channel == "autosave_parse"
    assert v.losses["player"] == {"archer": 6}
    assert v.survivors["player"]["archer"]["count"] == 14


def test_detect_outcome_loss_and_draw():
    spec = war_spec()
    a0 = {"index": 0, "name": "player", "alive": True, "gold": 0, "troops": {}}
    d0 = {"index": 1, "name": "l_hawk", "alive": True, "gold": 0, "troops": {}}
    # атакующий мёртв — loss
    v = detect_outcome(snap([a0, d0]), snap([dict(a0, alive=False), d0]), spec)
    assert v.outcome == "loss"
    # оба живы (тайм-аут) — draw
    v = detect_outcome(snap([a0, d0]), snap([a0, d0]), spec)
    assert v.outcome == "draw"


def test_detect_outcome_real_snapshots_degrade_to_manual():
    real_like = snap(None)
    v = detect_outcome(real_like, real_like, war_spec())
    assert v.outcome is None and v.channel == "manual"
    assert "G18" in v.reason


def test_read_bridge_outcome(tmp_path: Path):
    assert read_bridge_outcome(tmp_path) is None
    (tmp_path / "outcome.json").write_text(
        json.dumps({"scene_tag": "sc_1", "outcome": "win", "save": "auto.sh2"}),
        encoding="utf-8")
    assert read_bridge_outcome(tmp_path)["outcome"] == "win"
    (tmp_path / "outcome.json").write_text("{битый", encoding="utf-8")
    assert read_bridge_outcome(tmp_path) is None  # мост не ломает конвейер


def test_resolve_outcome_ladder_priority(tmp_path: Path):
    start = snap([{"index": 0, "name": "player", "alive": True, "gold": 0, "troops": {}},
                  {"index": 1, "name": "l_hawk", "alive": True, "gold": 0, "troops": {}}])
    end_win = snap([{"index": 0, "name": "player", "alive": True, "gold": 0, "troops": {}},
                    {"index": 1, "name": "l_hawk", "alive": False, "gold": 0, "troops": {}}])
    # мост приоритетнее автосейва
    (tmp_path / "outcome.json").write_text(
        json.dumps({"outcome": "loss"}), encoding="utf-8")
    v = resolve_outcome(war_spec(), bridge_dir=tmp_path,
                        start_snapshot=start, end_snapshot=end_win)
    assert v.outcome == "loss" and v.channel == "bridge"
    # без моста — автосейв
    v = resolve_outcome(war_spec(), start_snapshot=start, end_snapshot=end_win)
    assert v.outcome == "win" and v.channel == "autosave_parse"
    # без данных — manual; с выбором человека — manual
    v = resolve_outcome(war_spec(), start_snapshot=snap(None), end_snapshot=snap(None))
    assert v.outcome is None and v.channel == "manual"
    v = resolve_outcome(war_spec(), manual_choice="draw")
    assert v.outcome == "draw" and v.channel == "manual"


def test_manual_outcome_validates():
    assert manual_outcome("win").outcome == "win"
    with pytest.raises(ValueError):
        manual_outcome("победа")


def test_build_scene_result_contract():
    v = OutcomeVerdict("win", "autosave_parse", "test",
                       losses={"player": {"archer": 6}})
    r = build_scene_result("sc_0042", v, duration_real_min=34.0,
                           captures=["r07"], honour_delta=40,
                           development_damage={"r07": -1},
                           snapshot_end="snap_sc0042_end.json",
                           honesty={"pass": True, "report": "honesty_sc0042.json"})
    assert r["schema_version"] == "1.0" and r["scene_id"] == "sc_0042"
    assert r["outcome"] == "win" and r["outcome_channel"] == "autosave_parse"
    assert r["captures"] == ["r07"] and r["honour_delta"] == 40
    assert r["honesty"]["pass"] is True
    keys = {"schema_version", "scene_id", "outcome", "outcome_channel",
            "duration_real_min", "losses", "survivors", "captures",
            "honour_delta", "development_damage", "snapshot_end",
            "honesty", "anomalies"}
    assert keys <= set(r)  # контракт 03 §3.4


# ---------------------------------------------------------------- watchdog
def test_watchdog_no_process():
    st = check_process(None)
    assert st.running is False and st.crashed is False
    assert "не запускался" in st.events[0]


def test_watchdog_crash_and_mercy_rule():
    # завершившийся с кодом 1 процесс = краш; аномалия упоминает милосердие
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(1)"])
    proc.wait()
    rep = watchdog_report(proc)
    assert rep["crashed"] is True
    assert any("милосердие" in e for e in rep["events"])


def test_watchdog_clean_exit_not_crash():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    rep = watchdog_report(proc)
    assert rep["crashed"] is False and rep["returncode"] == 0


def test_watchdog_mem_limit_constant():
    assert MEM_LIMIT_MB == 1600.0  # 08 §8.9
