"""data/watchlist.csv の読み込みと cards テーブルへの取り込み。

CSV列(ヘッダは日本語・英語どちらでも可):
  category(カテゴリ), name_ja(日本語名), name_en(英語名), set_code(セット記号),
  card_number(カード番号), psa_grade(PSAグレード指定), enabled(有効フラグ)

psa_grade 空欄 = 生カード(raw)。enabled は 1/0, true/false, はい/いいえ を受け付ける。
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from . import db
from .config import Config
from .models import Card

_HEADER_ALIASES = {
    "category": "category", "カテゴリ": "category",
    "name_ja": "name_ja", "日本語名": "name_ja",
    "name_en": "name_en", "英語名": "name_en",
    "set_code": "set_code", "セット記号": "set_code",
    "card_number": "card_number", "カード番号": "card_number",
    "psa_grade": "psa_grade", "psaグレード指定": "psa_grade", "PSAグレード指定": "psa_grade",
    "enabled": "enabled", "有効フラグ": "enabled",
}

_TRUE_VALUES = {"1", "true", "yes", "y", "はい", "有効", "on"}


def _normalize_row(row: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in row.items():
        if k is None:
            continue
        key = _HEADER_ALIASES.get(k.strip()) or _HEADER_ALIASES.get(k.strip().lower())
        if key:
            out[key] = (v or "").strip()
    return out


def load_watchlist_csv(csv_path: str | Path) -> list[Card]:
    cards: list[Card] = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            row = _normalize_row(raw)
            if not row.get("name_en") and not row.get("name_ja"):
                continue
            psa = row.get("psa_grade") or ""
            enabled_raw = (row.get("enabled") or "1").lower()
            cards.append(
                Card(
                    category=row.get("category") or "pokemon",
                    name_ja=row.get("name_ja") or "",
                    name_en=row.get("name_en") or "",
                    set_code=(row.get("set_code") or None),
                    card_number=(row.get("card_number") or None),
                    psa_grade=int(float(psa)) if psa else None,
                    enabled=enabled_raw in _TRUE_VALUES,
                )
            )
    return cards


def import_watchlist(conn: sqlite3.Connection, cfg: Config, csv_path: str | Path | None = None) -> int:
    """watchlist.csv を cards テーブルに upsert。取り込んだ件数を返す。"""
    path = Path(csv_path) if csv_path else cfg.resolve_path("data/watchlist.csv")
    cards = load_watchlist_csv(path)
    enabled_categories = set(cfg.enabled_categories().keys())
    n = 0
    for card in cards:
        if card.category not in enabled_categories:
            continue
        card.id = db.upsert_card(conn, card)
        n += 1
    conn.commit()
    return n
