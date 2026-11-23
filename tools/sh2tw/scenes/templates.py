"""templates.py — реестр шаблонов карт (S3.0/S3.3; ТЗ 05 §5.8).

Шаблон — ванильная карта заказчика, из которой генератор собирает сцены:
  - копия в templates/maps/ (эталон в git, 00 §0.6) — источник по умолчанию;
  - либо карта из каталога игры Maps/ (game_map) — читается, не копируется.

Реестр templates/templates.json: [{template_id, source: {kind: repo|game_map,
file}, sha256?, roles: [field|siege|defense|theater|specialty]}].

Отбор (S3.0, человек утверждает): 2 полевые, 3 штурмовые, 2–3 театральные,
1–2 specialty. ДЕФОЛТНАЯ рекомендация (машиночитаемая, человек может
переутвердить) выводится из каталога ref/maps_catalog.csv (E.1): по типу
карты, числу замков/деревень и известным кандидатом плана (Strong and
Stable, Two Pronged Crown, Whitebear — 09 этап 0).
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from ..snapshot_builder import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = REPO_ROOT / "templates" / "maps"
REGISTRY_PATH = REPO_ROOT / "templates" / "templates.json"
CATALOG_CSV = REPO_ROOT / "ref" / "maps_catalog.csv"
SCENE_ROLES = ("field", "siege", "defense", "theater", "specialty")


class TemplateError(Exception):
    """Шаблон не найден/некорректен."""


@dataclass
class Template:
    template_id: str
    kind: str          # repo | game_map
    file: str          # имя файла (repo: в templates/maps/; game_map: в Maps/ игры)
    sha256: str | None
    roles: list[str]

    def resolve(self, game_maps_dir: Path | None = None) -> Path:
        if self.kind == "repo":
            p = TEMPLATES_DIR / self.file
        else:
            if game_maps_dir is None:
                raise TemplateError(
                    f"шаблон {self.template_id}: каталог игры не задан "
                    f"(config/project.ini → maps_dir_game)")
            p = Path(game_maps_dir) / self.file
        if not p.exists():
            raise TemplateError(f"шаблон {self.template_id}: файл не найден {p}")
        return p


def load_registry(path: Path | None = None) -> list[Template]:
    """Чтение templates/templates.json (создаёт структуру, если нет)."""
    p = Path(path) if path else REGISTRY_PATH
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    out: list[Template] = []
    for d in data.get("templates") or []:
        roles = [r for r in (d.get("roles") or []) if r in SCENE_ROLES]
        out.append(Template(template_id=str(d.get("template_id", "")),
                            kind=str(d.get("source", {}).get("kind", "repo")),
                            file=str(d.get("source", {}).get("file", "")),
                            sha256=d.get("sha256"),
                            roles=roles))
    if not out:
        raise TemplateError(f"{p}: реестр пуст")
    for t in out:
        if not t.template_id or not t.file:
            raise TemplateError(f"запись без template_id/file: {t}")
    return out


def save_registry(templates: list[Template], path: Path | None = None) -> None:
    p = Path(path) if path else REGISTRY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": "1.0", "templates": [
        {"template_id": t.template_id,
         "source": {"kind": t.kind, "file": t.file},
         "sha256": t.sha256, "roles": t.roles} for t in templates]}
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")


def add_repo_template(template_id: str, map_path: Path, roles: list[str],
                      verify_sha: bool = True) -> Template:
    """Копирует эталон в templates/maps/ и регистрирует (S3.1 процедура)."""
    map_path = Path(map_path)
    if not map_path.exists():
        raise TemplateError(f"нет файла {map_path}")
    for r in roles:
        if r not in SCENE_ROLES:
            raise TemplateError(f"роль {r!r} ∉ {SCENE_ROLES}")
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    dst = TEMPLATES_DIR / map_path.name
    if dst.exists() and dst.read_bytes() != map_path.read_bytes():
        raise TemplateError(f"{dst.name}: в templates/maps/ уже другой эталон")
    if not dst.exists():
        dst.write_bytes(map_path.read_bytes())
    sha = sha256_file(dst) if verify_sha else None
    return Template(template_id=template_id, kind="repo",
                    file=dst.name, sha256=sha, roles=list(roles))


# --------------------------------------------------- дефолтная рекомендация
def default_recommendations(catalog_csv: Path | None = None) -> dict[str, list[dict]]:
    """Машинная рекомендация отбора шаблонов из каталога S3.0 (E.1).

    Критерии (05 §5.8): field — kingmaker с ≥4 замками (простор); siege —
    war_custom с 1–2 замками (цель штурма); theater — kingmaker с ≥6
    замками и ≥4 деревнями (живые соседи); defense — war_custom с 1 замком.
    Кандидаты плана (Strong and Stable, Two Pronged Crown, Whitebear)
    приоритетны. Итог утверждает человек (S3.0 human_review).
    """
    p = Path(catalog_csv) if catalog_csv else CATALOG_CSV
    if not p.exists():
        return {}
    rows: list[dict] = []
    with p.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append({
                "filename": row["filename"],
                "map_type_name": row["map_type_name"],
                "castles": int(row["n_castle_markers"]),
                "villages": int(row["n_village_markers"]),
            })
    plan_candidates = {"Strong and Stable.s2m", "Two Pronged Crown.s2m",
                       "Whitebear.s2m"}

    def pick(pred, n, prefer_plan=True):
        chosen: list[dict] = []
        pool = [r for r in rows if pred(r)]
        if prefer_plan:
            chosen += [r for r in pool if r["filename"] in plan_candidates][:1]
        for r in sorted(pool, key=lambda r: (-r["castles"], -r["villages"], r["filename"])):
            if len(chosen) >= n:
                break
            if r not in chosen:
                chosen.append(r)
        return chosen

    return {
        "field": pick(lambda r: r["map_type_name"] == "kingmaker"
                      and r["castles"] >= 4, 2),
        "siege": pick(lambda r: r["map_type_name"] == "war_custom"
                      and 1 <= r["castles"] <= 2, 3),
        "theater": pick(lambda r: r["map_type_name"] == "kingmaker"
                        and r["castles"] >= 6 and r["villages"] >= 4, 3),
        "defense": pick(lambda r: r["map_type_name"] == "war_custom"
                        and r["castles"] >= 1, 2),
        "specialty": pick(lambda r: r["map_type_name"] == "peace_custom", 2),
    }


def template_for_role(role: str, game_maps_dir: Path | None = None) -> Template:
    """Шаблон по роли: реестр (если заполнен) → дефолтная рекомендация →
    fallback — игра-каталог (без копирования, kind=game_map)."""
    if role not in SCENE_ROLES:
        raise TemplateError(f"роль {role!r} ∉ {SCENE_ROLES}")
    try:
        reg = load_registry()
        for t in reg:
            if role in t.roles:
                t.resolve(game_maps_dir)  # проверка существования
                return t
    except TemplateError:
        pass
    recs = default_recommendations()
    for rec in recs.get(role, [])[:1]:
        return Template(template_id=f"tpl_{role}_default",
                        kind="game_map", file=rec["filename"],
                        sha256=None, roles=[role])
    raise TemplateError(f"роль {role!r}: ни реестр, ни каталог не дают шаблона "
                        f"(заполните ref/maps_catalog.csv через catalog-maps)")
