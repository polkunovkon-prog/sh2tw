"""Тесты фронтенда оболочки кампании (бриф C, экраны 1–4, ТЗ 07 §7.5).

Проверяем контракт статики без браузера: файлы существуют и не пусты, в
index.html есть якоря всех четырёх экранов, app.js использует все REST-роуты
бэка (07 §7.5) и идемпотентный request_id, внешних URL нет (офлайн-игра),
в style.css — палитра «пергамент» (07 §7.1).
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC_DIR = (Path(__file__).resolve().parents[1]
              / "tools" / "sh2tw" / "shell" / "static")
INDEX = STATIC_DIR / "index.html"
APP_JS = STATIC_DIR / "app.js"
STYLE = STATIC_DIR / "style.css"

# Экраны 07 §7.5 — обязательные секции вкладок.
SCREEN_IDS = ("screen-map", "screen-region", "screen-battle", "screen-results")

# REST-роуты бэка (api.py), которые фронт обязан использовать (бриф C).
# Для /api/region/{id}/* проверяем префикс и суффиксы путей.
API_ROUTES = (
    "/api/state",
    "/api/season/next",
    "/api/region/",
    "/develop",
    "/recruit",
    "/buy",
    "/api/battle/prepare",
    "/api/battle/scene",
    "/api/battle/autoresolve",
    "/api/scene/pending",
    "/api/scene/result",
    "/api/diplomacy",
    "/api/undo",
    "/api/offer/decide",
)


def _strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _strip_block_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _strip_js_comments(text: str) -> str:
    text = _strip_block_comments(text)
    return re.sub(r"//[^\n]*", "", text)


# ============================================================ файлы
def test_static_files_exist_and_not_empty():
    for path in (INDEX, APP_JS, STYLE):
        assert path.is_file(), f"нет файла {path}"
        assert path.stat().st_size > 0, f"пустой файл {path}"


# ============================================================ index.html
def test_html_has_all_screen_anchors():
    html = INDEX.read_text(encoding="utf-8")
    for screen in SCREEN_IDS:
        assert f'id="{screen}"' in html, f"нет якоря экрана {screen}"


def test_html_links_local_assets_only():
    html = _strip_html_comments(INDEX.read_text(encoding="utf-8"))
    assert 'src="app.js"' in html
    assert 'href="style.css"' in html


# ================================================================ app.js
def test_appjs_fetches_state_and_key_routes():
    js = APP_JS.read_text(encoding="utf-8")
    assert "fetch('/api/state'" in js
    assert "api/season/next" in js
    assert "api/offer/decide" in js


def test_appjs_uses_all_api_routes():
    js = APP_JS.read_text(encoding="utf-8")
    missing = [route for route in API_ROUTES if route not in js]
    assert not missing, f"app.js не использует роуты: {missing}"


def test_appjs_posts_carry_request_id():
    """Все POST-запросы идемпотентны по request_id (07 §7.5, бриф C)."""
    js = APP_JS.read_text(encoding="utf-8")
    assert "request_id" in js
    assert "randomUUID" in js


def test_appjs_has_unit_name_mapping():
    """Роспись гарнизона — на русском (бриф C, экран 2)."""
    js = APP_JS.read_text(encoding="utf-8")
    for unit in ("archer", "spearman", "maceman", "crossbowman", "pikeman",
                 "swordsman", "knight"):
        assert unit in js, f"нет маппинга юнита {unit}"
    for word in ("лучник", "копейщик", "пехотинец", "арбалетчик", "пикинёр",
                 "мечник", "рыцарь"):
        assert word in js, f"нет русского имени юнита «{word}»"


# ============================================================= офлайн
def test_no_external_urls_offline_game():
    """Внешних CDN/шрифтов/библиотек нет — офлайн-игра (бриф C)."""
    for path, strip in ((INDEX, _strip_html_comments),
                        (STYLE, _strip_block_comments),
                        (APP_JS, _strip_js_comments)):
        text = strip(path.read_text(encoding="utf-8"))
        for scheme in ("http://", "https://"):
            assert scheme not in text, \
                f"внешний URL {scheme} в {path.name}"


# ============================================================= style.css
def test_style_parchment_palette():
    css = STYLE.read_text(encoding="utf-8").lower()
    assert "#f0e6d2" in css or "#e8dcc0" in css
    # остальные цвета палитры 07 §7.1
    assert "#3b2f1e" in css, "нет чернильного текста"
    assert "#8b1a1a" in css, "нет красного акцента"
    assert "#2e5d34" in css, "нет тёмно-зелёного позитива"
    assert "#8a8070" in css, "нет серого неактива"
