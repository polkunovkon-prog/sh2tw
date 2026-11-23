"""ga_cli.py — полуавтоматический UX GA (S6.4; 08 §8.9): next/result/status.

Человек играет матчи; `next` показывает карту/сторону/доктрину следующего
матча, `result` — форма из 3 полей (исход W/L/D, потери атакующего, потери
обороняющего) → match_result_<id>.json в ga_runs/<run_id>/. Данные прогона —
ga_runs/<run_id>/queue.json. Отдельная точка входа (НЕ общий cli.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OUTCOMES = ("W", "L", "D")


def _run_dir(ga_root: str, run_id: str) -> Path:
    return Path(ga_root) / run_id


def _load_queue(run_dir: Path) -> dict | None:
    path = run_dir / "queue.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_queue(run_dir: Path, queue: dict) -> None:
    (run_dir / "queue.json").write_text(
        json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")


def _pending(queue: dict) -> list[dict]:
    return [m for m in queue.get("matches", [])
            if m.get("status") != "done"]


def _print_match(m: dict) -> None:
    print(f"Матч {m.get('match_id')}: карта {m.get('map', '?')}, "
          f"сторона {m.get('side', '?')}, доктрина {m.get('doctrine_id', '?')}"
          f", оборона {m.get('defense_id', '?')}")


def _cmd_next(run_dir: Path) -> int:
    queue = _load_queue(run_dir)
    if queue is None:
        print(f"нет очереди: {run_dir / 'queue.json'} — инициализируйте "
              f"прогон", file=sys.stderr)
        return 2
    pending = _pending(queue)
    if not pending:
        print("все матчи закрыты — очередь пуста")
        return 0
    _print_match(pending[0])
    return 0


def _cmd_status(run_dir: Path) -> int:
    queue = _load_queue(run_dir)
    if queue is None:
        print(f"нет очереди: {run_dir / 'queue.json'}", file=sys.stderr)
        return 2
    matches = queue.get("matches", [])
    done = [m for m in matches if m.get("status") == "done"]
    print(f"Прогон {queue.get('run_id', '?')}: закрыто "
          f"{len(done)}/{len(matches)} матчей")
    champion_path = run_dir / "champion.json"
    if champion_path.is_file():
        champion = json.loads(champion_path.read_text(encoding="utf-8"))
        print(f"Чемпион: fitness {champion.get('fitness')}, поколение "
              f"{champion.get('generation')}")
    return 0


def _ask_choice(prompt: str, choices: tuple[str, ...]) -> str:
    while True:
        answer = input(prompt).strip().upper()
        if answer in choices:
            return answer
        print(f"  допустимо: {'/'.join(choices)}")


def _ask_int(prompt: str) -> int:
    while True:
        answer = input(prompt).strip()
        try:
            value = int(answer)
        except ValueError:
            print("  ожидалось целое число ≥ 0")
            continue
        if value >= 0:
            return value
        print("  ожидалось целое число ≥ 0")


def _cmd_result(run_dir: Path, args: argparse.Namespace) -> int:
    queue = _load_queue(run_dir)
    if queue is None:
        print(f"нет очереди: {run_dir / 'queue.json'}", file=sys.stderr)
        return 2
    pending = _pending(queue)
    if args.match:
        target = next((m for m in pending if m.get("match_id") == args.match),
                      None)
        if target is None:
            print(f"матч {args.match!r} не в ожидании (нет или уже закрыт)",
                  file=sys.stderr)
            return 2
    elif pending:
        target = pending[0]
    else:
        print("нет открытых матчей — очередь пуста", file=sys.stderr)
        return 2

    outcome = args.outcome
    attacker_losses = args.attacker_losses
    defender_losses = args.defender_losses
    if outcome is None:  # интерактивная форма из 3 полей (08 §8.9)
        outcome = _ask_choice("Исход (W/L/D): ", OUTCOMES)
        attacker_losses = _ask_int("Потери атакующего: ")
        defender_losses = _ask_int("Потери обороняющего: ")
    outcome = str(outcome).upper()
    if outcome not in OUTCOMES:
        print(f"исход {outcome!r} ∉ {'/'.join(OUTCOMES)}", file=sys.stderr)
        return 2
    for name, value in (("attacker_losses", attacker_losses),
                        ("defender_losses", defender_losses)):
        if not isinstance(value, int) or value < 0:
            print(f"{name}: целое ≥ 0", file=sys.stderr)
            return 2

    record = {"match_id": target.get("match_id"), "outcome": outcome,
              "attacker_losses": int(attacker_losses),
              "defender_losses": int(defender_losses),
              "source": "human"}
    result_path = run_dir / f"match_result_{target['match_id']}.json"
    result_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    target["status"] = "done"
    _save_queue(run_dir, queue)
    print(f"Записан результат {target['match_id']}: {outcome}, потери "
          f"{record['attacker_losses']}/{record['defender_losses']} → "
          f"{result_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Точка входа: python -m sh2tw.ga.ga_cli --run <run_id> next|result|status."""
    parser = argparse.ArgumentParser(
        prog="python -m sh2tw.ga.ga_cli",
        description="Полуавтомат GA-конвейера: next/result/status (08 §8.9)")
    parser.add_argument("--run", required=True,
                        help="идентификатор прогона (ga_runs/<run_id>)")
    parser.add_argument("--ga-root", default="ga_runs",
                        help="корень каталогов прогонов (по умолчанию ga_runs)")
    parser.add_argument("command", choices=("next", "result", "status"))
    parser.add_argument("--match", help="id матча (по умолчанию первый открытый)")
    parser.add_argument("--outcome", choices=list(OUTCOMES),
                        help="исход W/L/D (иначе интерактивный ввод)")
    parser.add_argument("--attacker-losses", type=int,
                        help="потери атакующего (для result)")
    parser.add_argument("--defender-losses", type=int,
                        help="потери обороняющего (для result)")
    args = parser.parse_args(argv)
    run_dir = _run_dir(args.ga_root, args.run)
    if args.command == "next":
        return _cmd_next(run_dir)
    if args.command == "status":
        return _cmd_status(run_dir)
    return _cmd_result(run_dir, args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
