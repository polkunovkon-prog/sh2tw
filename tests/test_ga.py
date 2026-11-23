"""Тесты S6.1–S6.4: GA — фитнес, движок, пул прогонов, полуавтомат CLI.

Игрушечная задача сходимости: ScriptedSource с вероятностью победы,
зависящей от first_attack_month (оптимум 15) + детерминированный градиент
потерь/времени; проверяется, что чемпион ближе к оптимуму, чем стартовый
сид, и что прогоны полностью детерминированы (один сид → один лог).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from sh2tw.doctrines.doctrine import load_doctrine, save_doctrine, \
    validate_genome
from sh2tw.ga import ga_cli
from sh2tw.ga.engine import (GENES, GaError, crossover, genome_to_doctrine,
                             load_ga_config, mutate, random_genome, run_ga)
from sh2tw.ga.fitness import aggregate, fitness
from sh2tw.ga.runner_pool import (HEARTBEAT_STALE_SEC, MEM_LIMIT_MB,
                                  InstancePool, MatchRunner, ScriptedSource,
                                  SemiAutoSource)

WIN_MATCH = {"win": True, "time_min": 30.0, "losses_pct": 0.2,
             "breakthrough": False, "wall_abuse": 0, "honesty_violations": 0}
LOSS_MATCH = {"win": False, "time_min": 30.0, "losses_pct": 0.3,
              "breakthrough": False, "wall_abuse": 0, "honesty_violations": 0}


# ------------------------------------------------------------------- фитнес
def test_fitness_clean_win_positive():
    assert fitness(dict(WIN_MATCH)) == pytest.approx(100 - 15 - 6)
    assert fitness(dict(WIN_MATCH)) > 0


def test_fitness_violation_is_minus_inf():
    bad = dict(WIN_MATCH, honesty_violations=1)
    assert fitness(bad) == float("-inf")


def test_fitness_wall_abuse_penalizes():
    abused = dict(WIN_MATCH, wall_abuse=True)
    assert fitness(abused) == pytest.approx(fitness(WIN_MATCH) - 20)
    assert fitness(dict(WIN_MATCH, wall_abuse=2)) == \
        pytest.approx(fitness(WIN_MATCH) - 40)


def test_fitness_breakthrough_and_losses():
    assert fitness(dict(WIN_MATCH, breakthrough=True)) == \
        pytest.approx(fitness(WIN_MATCH) + 15)
    assert fitness(dict(WIN_MATCH, losses_pct=0.5)) == \
        pytest.approx(fitness(WIN_MATCH) - 9)
    with pytest.raises(ValueError):
        fitness("not-a-match")


def test_aggregate_lexicographic_honesty_first():
    two_wins_with_violation = aggregate(
        [dict(WIN_MATCH), dict(WIN_MATCH),
         dict(WIN_MATCH, honesty_violations=2)])
    zero_wins_clean = aggregate([dict(LOSS_MATCH), dict(LOSS_MATCH)])
    assert two_wins_with_violation["honesty_violations"] == 2
    assert len(two_wins_with_violation["quarantined"]) == 1
    assert two_wins_with_violation["wins"] == 2  # карантин не в зачёт побед
    # 2 победы + нарушение ХУЖЕ 0 побед без нарушений (08 §8.8)
    assert two_wins_with_violation["fitness_mean"] == float("-inf")
    assert zero_wins_clean["fitness_mean"] > two_wins_with_violation["fitness_mean"]
    assert two_wins_with_violation["lex_key"] > zero_wins_clean["lex_key"]


def test_aggregate_aborted_not_counted():
    result = aggregate([dict(WIN_MATCH, aborted=True), dict(WIN_MATCH)])
    assert result["wins"] == 1
    assert result["matches"] == 1
    assert len(result["aborted"]) == 1
    assert result["honesty_violations"] == 0


# ------------------------------------------------------------------- движок
def toy_cfg() -> dict:
    return {"population": 6, "generations_max": 3, "elitism": 2,
            "selection": {"kind": "tournament", "k": 3},
            "mutation": {"sigma_rel": 0.3, "gene_prob": 0.5},
            "crossover": "uniform",
            "stop": {"winrate_plateau_generations": 5}}


def toy_evaluate(genome: dict) -> dict:
    """Матч: p(победы) зависит от first_attack_month (оптимум 15)."""
    first = genome["first_attack_month"]
    p = max(0.05, 1.0 - abs(first - 15) / 30.0)
    match = MatchRunner(ScriptedSource(win_probability=p, seed=7)).run_match(
        genome, "def_hedgehog")
    distance = abs(first - 15)
    match["losses_pct"] = distance / 100.0   # детерминированный градиент
    match["time_min"] = 20.0 + 0.5 * distance
    return match


def test_ga_config_yaml_defaults():
    cfg = load_ga_config()  # ga_config.yaml в корне репо
    assert cfg["population"] == 12 and cfg["generations_max"] == 20
    assert cfg["matches_per_candidate"] == 3 and cfg["elitism"] == 2
    assert cfg["mutation"]["sigma_rel"] == 0.15
    assert cfg["mutation"]["gene_prob"] == 0.3
    assert cfg["selection"] == {"kind": "tournament", "k": 3}
    assert cfg["stop"]["winrate_plateau_generations"] == 5
    assert len(cfg["defenses_portfolio"]) == 3
    assert cfg["crossover"] == "uniform" and cfg["instances"] == 2


def test_genes_match_contract():
    assert len(GENES) == 23  # ~25 генов 08 §8.3 (полный список контракта)
    by_name = {g.name: g for g in GENES}
    assert by_name["first_attack_month"].minimum == 6
    assert by_name["first_attack_month"].maximum == 30
    assert by_name["breach_target"].choices == ("gate", "wall")
    assert by_name["aic_key"].kind == "enum"


def test_random_genome_valid_and_mutate_clamps():
    for seed in range(10):
        assert validate_genome(random_genome(random.Random(seed)))
    cfg = {"mutation": {"sigma_rel": 50.0, "gene_prob": 1.0}}
    mutated = mutate(random_genome(random.Random(1)), cfg, random.Random(2))
    assert validate_genome(mutated)  # клампы удержали все гены в границах


def test_crossover_uniform():
    a = random_genome(random.Random(3))
    b = random_genome(random.Random(4))
    child = crossover(a, b, random.Random(5))
    assert set(child) == set(a)
    assert all(child[k] in (a[k], b[k]) for k in child)
    assert crossover(a, b) == crossover(a, b)  # детерминированное чередование


def test_run_ga_errors():
    with pytest.raises(GaError):
        run_ga({"population": 1}, toy_evaluate, random.Random(1))
    with pytest.raises(GaError):
        run_ga({"population": 4, "selection": {"kind": "roulette"}},
               toy_evaluate, random.Random(1))
    with pytest.raises(GaError):
        run_ga(toy_cfg(), toy_evaluate, random.Random(1),
               seed_genome=valid_genome_bad())


def valid_genome_bad() -> dict:
    genome = random_genome(random.Random(9))
    genome["first_attack_month"] = 99
    return genome


def test_run_ga_toy_convergence(tmp_path):
    seed_genome = random_genome(random.Random(11))
    seed_genome["first_attack_month"] = 8
    out = run_ga(toy_cfg(), toy_evaluate, random.Random(8),
                 seed_genome=seed_genome, run_id="toy", run_root=tmp_path)
    champion = out["champion"]
    assert champion is not None
    assert validate_genome(champion["genome"])
    # чемпион ближе к оптимуму 15, чем стартовый сид (8 → |d|=7)
    assert abs(champion["genome"]["first_attack_month"] - 15) < 7
    run_dir = tmp_path / "toy"
    assert (run_dir / "population_gen_000.json").is_file()
    assert (run_dir / "run_log.json").is_file()
    assert (run_dir / "champion.json").is_file()
    log = out["run_log"]
    assert 1 <= len(log["hall_of_fame"]) <= 10
    assert log["hall_of_fame"][0]["genome"] == champion["genome"]
    assert log["stopped_reason"] in ("plateau", "generations_max")
    written = json.loads((run_dir / "population_gen_000.json")
                         .read_text(encoding="utf-8"))
    assert len(written["population"]) == 6
    assert len(log["generations"]) == log["generations_run"] <= 3


def test_run_ga_determinism(tmp_path):
    seed_genome = random_genome(random.Random(11))
    seed_genome["first_attack_month"] = 8
    out1 = run_ga(toy_cfg(), toy_evaluate, random.Random(42),
                  seed_genome=dict(seed_genome), run_id="det",
                  run_root=tmp_path / "a")
    out2 = run_ga(toy_cfg(), toy_evaluate, random.Random(42),
                  seed_genome=dict(seed_genome), run_id="det",
                  run_root=tmp_path / "b")
    assert out1["run_log"] == out2["run_log"]  # один сид → одинаковый лог
    assert out1["champion"] == out2["champion"]


def test_run_ga_plateau_stop(tmp_path):
    cfg = {"population": 4, "generations_max": 20, "elitism": 2,
           "selection": {"kind": "tournament", "k": 3},
           "mutation": {"sigma_rel": 0.15, "gene_prob": 0.3},
           "crossover": "uniform",
           "stop": {"winrate_plateau_generations": 5}}
    constant = lambda genome: dict(LOSS_MATCH)  # noqa: E731 — фитнес константен
    out = run_ga(cfg, constant, random.Random(1), run_id="plateau",
                 run_root=tmp_path)
    log = out["run_log"]
    assert log["stopped_reason"] == "plateau"
    assert log["generations_run"] == 6  # gen0 улучшение + 5 без улучшения
    assert log["champion"]["fitness"] == pytest.approx(fitness(LOSS_MATCH))
    files = sorted((tmp_path / "plateau").glob("population_gen_*.json"))
    assert len(files) == 6


def test_genome_to_doctrine_roundtrip(tmp_path):
    doctrine = genome_to_doctrine(random_genome(random.Random(5)), "sieger")
    assert doctrine["provenance"]["origin"] == "ga"
    assert doctrine["invasion_choreography"]  # волны из генома
    saved = save_doctrine(doctrine, tmp_path / "ga_doctrine.yaml")
    assert load_doctrine(saved) == doctrine


# ------------------------------------------------------------- пул прогонов
def test_scripted_source_deterministic():
    genome = random_genome(random.Random(2))
    runner = MatchRunner(ScriptedSource(win_probability=0.7, seed=9))
    m1 = runner.run_match(genome, "def_hedgehog")
    m2 = runner.run_match(genome, "def_hedgehog")
    assert m1 == m2
    assert m1["simulated"] is True and m1["aborted"] is False
    assert m1["watchdog"]["memory_limit_mb"] == MEM_LIMIT_MB == 1600
    assert m1["watchdog"]["heartbeat_stale_sec"] == HEARTBEAT_STALE_SEC == 180
    other = runner.run_match(genome, "def_archers")  # другая оборона — др. сид
    assert other["seed"] == m1["seed"] and other["outcome"] in ("W", "L")
    genome2 = random_genome(random.Random(3))
    assert runner.run_match(genome2, "def_hedgehog")["seed"] != m1["seed"]


def test_scripted_source_probability_bounds():
    with pytest.raises(ValueError):
        ScriptedSource(win_probability=1.5)


def test_semi_auto_source(tmp_path):
    source = SemiAutoSource(tmp_path)
    pending = source.resolve({"match_id": "m001", "seed": "s"})
    assert pending["status"] == "pending_human"
    (tmp_path / "match_result_m001.json").write_text(json.dumps(
        {"outcome": "W", "attacker_losses": 10, "defender_losses": 30}),
        encoding="utf-8")
    resolved = source.resolve({"match_id": "m001", "seed": "s"})
    assert resolved["win"] is True and resolved["source"] == "human"
    assert resolved["losses_pct"] == pytest.approx(0.25)


def test_instance_pool_slots():
    pool = InstancePool(instances=2)
    a, b = pool.acquire(), pool.acquire()
    assert a and b and a != b
    assert pool.acquire() is None  # все слоты заняты
    assert pool.release(a) is True
    assert pool.acquire() == a
    assert "stub" in pool.as_dict()["sandboxie"]


# ------------------------------------------------------------- полуавтомат CLI
@pytest.fixture()
def cli_run(tmp_path):
    run_dir = tmp_path / "test"
    run_dir.mkdir()
    queue = {"run_id": "test", "matches": [
        {"match_id": "m001", "map": "S2TW_field_01", "side": "attacker",
         "doctrine_id": "doc_sieger_v2", "defense_id": "def_hedgehog",
         "status": "pending"},
        {"match_id": "m002", "map": "S2TW_field_01", "side": "attacker",
         "doctrine_id": "doc_sieger_v2", "defense_id": "def_archers",
         "status": "pending"}]}
    (run_dir / "queue.json").write_text(json.dumps(queue), encoding="utf-8")
    return tmp_path


def _cli(root: Path, *args) -> int:
    return ga_cli.main(["--run", "test", "--ga-root", str(root), *args])


def test_ga_cli_next_status_result_cycle(cli_run, capsys):
    assert _cli(cli_run, "next") == 0
    out = capsys.readouterr().out
    assert "m001" in out and "S2TW_field_01" in out and "doc_sieger_v2" in out
    assert _cli(cli_run, "status") == 0
    assert "0/2" in capsys.readouterr().out
    rc = _cli(cli_run, "result", "--match", "m001", "--outcome", "W",
              "--attacker-losses", "10", "--defender-losses", "25")
    assert rc == 0
    record = json.loads((cli_run / "test" / "match_result_m001.json")
                        .read_text(encoding="utf-8"))
    assert record == {"match_id": "m001", "outcome": "W",
                      "attacker_losses": 10, "defender_losses": 25,
                      "source": "human"}
    assert _cli(cli_run, "status") == 0
    assert "1/2" in capsys.readouterr().out
    assert _cli(cli_run, "next") == 0
    assert "m002" in capsys.readouterr().out
    # result без --match закрывает первый открытый матч
    assert _cli(cli_run, "result", "--outcome", "L",
                "--attacker-losses", "30", "--defender-losses", "5") == 0
    assert _cli(cli_run, "status") == 0
    assert "2/2" in capsys.readouterr().out
    assert _cli(cli_run, "next") == 0
    assert "пуста" in capsys.readouterr().out


def test_ga_cli_rejects_bad_input(cli_run, capsys):
    with pytest.raises(SystemExit) as exc:  # argparse-уровень: недопустимый исход
        _cli(cli_run, "result", "--outcome", "X")
    assert exc.value.code == 2
    assert _cli(cli_run, "result", "--match", "nope", "--outcome", "W") == 2
    assert _cli(cli_run, "result", "--outcome", "W",
                "--attacker-losses", "-5") == 2
    assert ga_cli.main(["--run", "ghost", "--ga-root", str(cli_run),
                        "next"]) == 2  # нет очереди
