"""SQLite スキーマとデータアクセス層。

Streamlit ダッシュボードも将来の React 化もこのモジュール経由でデータを読む前提
(UI から直接 SQL を書かない)。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import (
    Card,
    Deal,
    EbaySoldListing,
    MarketStats,
    MercariListing,
    ProfitResult,
    SnkrdunkListing,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id            INTEGER PRIMARY KEY,
    category      TEXT NOT NULL DEFAULT 'pokemon',
    name_ja       TEXT NOT NULL,
    name_en       TEXT NOT NULL,
    set_code      TEXT,
    card_number   TEXT,
    psa_grade     INTEGER,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    UNIQUE(category, name_en, set_code, card_number, psa_grade)
);

CREATE TABLE IF NOT EXISTS listings_ebay_sold (
    id               INTEGER PRIMARY KEY,
    card_id          INTEGER REFERENCES cards(id),
    title            TEXT NOT NULL,
    price_usd        REAL NOT NULL,
    shipping_usd     REAL NOT NULL DEFAULT 0,
    sold_at          TEXT,
    image_url        TEXT,
    listing_url      TEXT NOT NULL,
    psa_grade        INTEGER,
    match_confidence TEXT NOT NULL DEFAULT 'none',
    raw_query        TEXT,
    scraped_at       TEXT NOT NULL,
    UNIQUE(listing_url, sold_at)
);

CREATE TABLE IF NOT EXISTS listings_mercari (
    id               INTEGER PRIMARY KEY,
    card_id          INTEGER REFERENCES cards(id),
    title            TEXT NOT NULL,
    price_jpy        INTEGER NOT NULL,
    condition        TEXT,
    image_url        TEXT,
    listing_url      TEXT NOT NULL UNIQUE,
    listed_at        TEXT,
    match_confidence TEXT NOT NULL DEFAULT 'none',
    raw_query        TEXT,
    scraped_at       TEXT NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS listings_snkrdunk (
    id               INTEGER PRIMARY KEY,
    card_id          INTEGER REFERENCES cards(id),
    product_name     TEXT NOT NULL,
    min_price_jpy    INTEGER NOT NULL,
    product_url      TEXT NOT NULL UNIQUE,
    image_url        TEXT,
    match_confidence TEXT NOT NULL DEFAULT 'none',
    raw_query        TEXT,
    scraped_at       TEXT NOT NULL
);

-- 毎回のパイプライン実行で全削除→再構築する「計算結果」テーブル
CREATE TABLE IF NOT EXISTS matches (
    id                INTEGER PRIMARY KEY,
    card_id           INTEGER NOT NULL REFERENCES cards(id),
    source            TEXT NOT NULL,             -- 'mercari' | 'snkrdunk'
    source_listing_id INTEGER NOT NULL,
    confidence        TEXT NOT NULL,
    ebay_median_usd   REAL NOT NULL,
    ebay_count_30d    INTEGER NOT NULL,
    ebay_min_usd      REAL NOT NULL,
    ebay_max_usd      REAL NOT NULL,
    reliability       TEXT NOT NULL,             -- 'ok' | 'low'
    buy_total_jpy     REAL NOT NULL,
    revenue_jpy       REAL NOT NULL,
    ebay_fees_jpy     REAL NOT NULL,
    ship_out_jpy      REAL NOT NULL,
    profit_jpy        REAL NOT NULL,
    profit_rate       REAL NOT NULL,
    fx_rate           REAL NOT NULL,
    computed_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fx_rates (
    id         INTEGER PRIMARY KEY,
    pair       TEXT NOT NULL,      -- 'USDJPY'
    rate       REAL NOT NULL,
    fetched_at TEXT NOT NULL
);

-- ダッシュボードで「無視」した出品。listing_url 単位で以後非表示・非通知
CREATE TABLE IF NOT EXISTS ignore_list (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    listing_url TEXT NOT NULL UNIQUE,
    note        TEXT,
    created_at  TEXT NOT NULL
);

-- Discord通知済みの出品。再通知を防ぐ
CREATE TABLE IF NOT EXISTS notified_deals (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    listing_url TEXT NOT NULL UNIQUE,
    notified_at TEXT NOT NULL
);

-- スクレイプ実行ログ(失敗の可視化用)
CREATE TABLE IF NOT EXISTS scrape_runs (
    id             INTEGER PRIMARY KEY,
    source         TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    queries_total  INTEGER NOT NULL DEFAULT 0,
    queries_failed INTEGER NOT NULL DEFAULT 0,
    items_found    INTEGER NOT NULL DEFAULT 0,
    parse_failures INTEGER NOT NULL DEFAULT 0,
    notes          TEXT
);

CREATE INDEX IF NOT EXISTS idx_ebay_card_sold ON listings_ebay_sold(card_id, sold_at);
CREATE INDEX IF NOT EXISTS idx_mercari_card ON listings_mercari(card_id);
CREATE INDEX IF NOT EXISTS idx_matches_card ON matches(card_id);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# confidence の強さ順。SQL 内で「より確度の高い判定だけが既存行を上書きできる」
# 比較に使う(同一出品が複数 watchlist カードのクエリ結果に現れるため、
# 処理順による先勝ち/後勝ちではなく最良マッチ勝ちにする)。
_CONF_RANK_SQL = "CASE {col} WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END"


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------- cards

def upsert_card(conn: sqlite3.Connection, card: Card) -> int:
    """watchlist からの取り込み。既存なら enabled/name_ja を更新して id を返す。

    SQLite の UNIQUE 制約は NULL 同士を別値として扱うため(set_code/psa_grade が
    NULL のカードで ON CONFLICT が発火しない)、IS 比較による手動 upsert にしている。
    """
    row = conn.execute(
        "SELECT id FROM cards WHERE category=? AND name_en=? AND set_code IS ? AND card_number IS ? AND psa_grade IS ?",
        (card.category, card.name_en, card.set_code, card.card_number, card.psa_grade),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE cards SET name_ja = ?, enabled = ? WHERE id = ?",
            (card.name_ja, 1 if card.enabled else 0, row["id"]),
        )
        return int(row["id"])
    cur = conn.execute(
        """
        INSERT INTO cards (category, name_ja, name_en, set_code, card_number, psa_grade, enabled, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            card.category,
            card.name_ja,
            card.name_en,
            card.set_code,
            card.card_number,
            card.psa_grade,
            1 if card.enabled else 0,
            utcnow(),
        ),
    )
    return int(cur.lastrowid)


def _row_to_card(row: sqlite3.Row) -> Card:
    return Card(
        id=row["id"],
        category=row["category"],
        name_ja=row["name_ja"],
        name_en=row["name_en"],
        set_code=row["set_code"],
        card_number=row["card_number"],
        psa_grade=row["psa_grade"],
        enabled=bool(row["enabled"]),
    )


def list_cards(conn: sqlite3.Connection, enabled_only: bool = True) -> list[Card]:
    sql = "SELECT * FROM cards"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY category, name_en"
    return [_row_to_card(r) for r in conn.execute(sql).fetchall()]


def get_card(conn: sqlite3.Connection, card_id: int) -> Optional[Card]:
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return _row_to_card(row) if row else None


# ------------------------------------------------------- listings: ebay

def insert_ebay_sold(conn: sqlite3.Connection, items: Iterable[EbaySoldListing]) -> int:
    """重複(listing_url + sold_at)は confidence の高い判定だけが上書きできる。

    同一落札が複数 watchlist カード(raw と PSA10 指定など)のクエリ結果に現れるため、
    先勝ちの INSERT OR IGNORE だと 'none' 判定が枠を恒久占有し、正当な high 判定が
    捨てられる。confidence ランクが厳密に上のときのみ card_id/判定を付け替える。
    sold_at が NULL の行は UNIQUE 制約で重複排除できない(SQLite は NULL 同士を
    別値扱いする)ため、IS NULL の存在チェックを先に行う。
    戻り値は新規挿入+格上げ更新の件数。
    """
    n = 0
    now = utcnow()
    rank_new = _CONF_RANK_SQL.format(col="excluded.match_confidence")
    rank_old = _CONF_RANK_SQL.format(col="listings_ebay_sold.match_confidence")
    for it in items:
        if it.sold_at is None:
            exists = conn.execute(
                "SELECT 1 FROM listings_ebay_sold WHERE listing_url = ? AND sold_at IS NULL",
                (it.listing_url,),
            ).fetchone()
            if exists:
                continue
        cur = conn.execute(
            f"""
            INSERT INTO listings_ebay_sold
                (card_id, title, price_usd, shipping_usd, sold_at, image_url,
                 listing_url, psa_grade, match_confidence, raw_query, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(listing_url, sold_at) DO UPDATE SET
                card_id = excluded.card_id,
                match_confidence = excluded.match_confidence,
                raw_query = excluded.raw_query,
                scraped_at = excluded.scraped_at
            WHERE {rank_new} > {rank_old}
            """,
            (
                it.card_id, it.title, it.price_usd, it.shipping_usd, it.sold_at,
                it.image_url, it.listing_url, it.psa_grade, it.match_confidence,
                it.raw_query, now,
            ),
        )
        n += cur.rowcount if cur.rowcount > 0 else 0
    return n


def ebay_sold_for_card(
    conn: sqlite3.Connection,
    card_id: int,
    since_date: str,
    min_confidence: tuple[str, ...] = ("high", "medium"),
) -> list[sqlite3.Row]:
    """指定カードの since_date 以降の落札行。sold_at が NULL の行は除外。"""
    marks = ",".join("?" for _ in min_confidence)
    return conn.execute(
        f"""
        SELECT * FROM listings_ebay_sold
        WHERE card_id = ? AND sold_at IS NOT NULL AND sold_at >= ?
          AND match_confidence IN ({marks})
        ORDER BY sold_at DESC
        """,
        (card_id, since_date, *min_confidence),
    ).fetchall()


# ---------------------------------------------------- listings: mercari

def upsert_mercari(conn: sqlite3.Connection, items: Iterable[MercariListing]) -> int:
    """価格・取得時刻・active は無条件更新。card_id と confidence は
    「同一カードの再スクレイプ」または「より高い confidence の判定」のときだけ
    上書きする(別カードのクエリ結果に同じ出品が混ざったとき、'none' 判定が
    他カードの high マッチを壊すのを防ぐ。処理順に依存しない最良マッチ勝ち)。
    """
    n = 0
    now = utcnow()
    rank_new = _CONF_RANK_SQL.format(col="excluded.match_confidence")
    rank_old = _CONF_RANK_SQL.format(col="listings_mercari.match_confidence")
    better = f"(listings_mercari.card_id IS excluded.card_id OR {rank_new} > {rank_old})"
    for it in items:
        conn.execute(
            f"""
            INSERT INTO listings_mercari
                (card_id, title, price_jpy, condition, image_url, listing_url,
                 listed_at, match_confidence, raw_query, scraped_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(listing_url) DO UPDATE SET
                price_jpy = excluded.price_jpy,
                scraped_at = excluded.scraped_at,
                active = 1,
                card_id = CASE WHEN {better} THEN excluded.card_id
                          ELSE listings_mercari.card_id END,
                match_confidence = CASE WHEN {better} THEN excluded.match_confidence
                                   ELSE listings_mercari.match_confidence END
            """,
            (
                it.card_id, it.title, it.price_jpy, it.condition, it.image_url,
                it.listing_url, it.listed_at, it.match_confidence, it.raw_query, now,
            ),
        )
        n += 1
    return n


def deactivate_stale_mercari(
    conn: sqlite3.Connection,
    scraped_before: str,
    exclude_card_ids: Iterable[int] = (),
) -> int:
    """今回の実行で見えなかった出品(売切れ/削除想定)を active=0 にする。

    exclude_card_ids: クエリ自体が失敗したカードの id。取得できなかっただけで
    売切れとは限らないため、失効対象から除外する。
    """
    exclude = [int(i) for i in exclude_card_ids if i is not None]
    sql = "UPDATE listings_mercari SET active = 0 WHERE scraped_at < ?"
    params: list[Any] = [scraped_before]
    if exclude:
        marks = ",".join("?" for _ in exclude)
        sql += f" AND (card_id IS NULL OR card_id NOT IN ({marks}))"
        params.extend(exclude)
    cur = conn.execute(sql, params)
    return cur.rowcount


# -------------------------------------------------- listings: snkrdunk

def upsert_snkrdunk(conn: sqlite3.Connection, items: Iterable[SnkrdunkListing]) -> int:
    """card_id/confidence の上書きルールは upsert_mercari と同じ(最良マッチ勝ち)。"""
    n = 0
    now = utcnow()
    rank_new = _CONF_RANK_SQL.format(col="excluded.match_confidence")
    rank_old = _CONF_RANK_SQL.format(col="listings_snkrdunk.match_confidence")
    better = f"(listings_snkrdunk.card_id IS excluded.card_id OR {rank_new} > {rank_old})"
    for it in items:
        conn.execute(
            f"""
            INSERT INTO listings_snkrdunk
                (card_id, product_name, min_price_jpy, product_url, image_url,
                 match_confidence, raw_query, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_url) DO UPDATE SET
                min_price_jpy = excluded.min_price_jpy,
                scraped_at = excluded.scraped_at,
                card_id = CASE WHEN {better} THEN excluded.card_id
                          ELSE listings_snkrdunk.card_id END,
                match_confidence = CASE WHEN {better} THEN excluded.match_confidence
                                   ELSE listings_snkrdunk.match_confidence END
            """,
            (
                it.card_id, it.product_name, it.min_price_jpy, it.product_url,
                it.image_url, it.match_confidence, it.raw_query, now,
            ),
        )
        n += 1
    return n


# ------------------------------------------------------------- matches

def rebuild_matches(conn: sqlite3.Connection, deals: Iterable[Deal]) -> int:
    """matches テーブルを全削除して deals で作り直す。"""
    conn.execute("DELETE FROM matches")
    n = 0
    now = utcnow()
    for d in deals:
        conn.execute(
            """
            INSERT INTO matches
                (card_id, source, source_listing_id, confidence,
                 ebay_median_usd, ebay_count_30d, ebay_min_usd, ebay_max_usd, reliability,
                 buy_total_jpy, revenue_jpy, ebay_fees_jpy, ship_out_jpy,
                 profit_jpy, profit_rate, fx_rate, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                d.card.id, d.source, d.source_listing_id, d.confidence,
                d.stats.median_usd, d.stats.count, d.stats.min_usd, d.stats.max_usd,
                d.stats.reliability,
                d.profit.buy_total_jpy, d.profit.revenue_jpy, d.profit.ebay_fees_jpy,
                d.profit.ship_out_jpy, d.profit.profit_jpy, d.profit.profit_rate,
                d.profit.fx_rate, now,
            ),
        )
        n += 1
    return n


def list_deals(
    conn: sqlite3.Connection,
    min_profit_rate: float | None = None,
    min_profit_jpy: float | None = None,
    confidences: tuple[str, ...] | None = None,
    psa_only: bool = False,
    category: str | None = None,
    include_low_reliability: bool = True,
    exclude_ignored: bool = True,
) -> list[dict[str, Any]]:
    """ダッシュボード/通知用: matches を出品情報・カード情報と JOIN して返す。

    返る dict のキー:
      card_id, category, card_name, name_en, set_code, card_number, psa_grade,
      source, title, buy_price_jpy, listing_url, image_url, confidence,
      ebay_median_usd, ebay_count_30d, ebay_min_usd, ebay_max_usd, reliability,
      buy_total_jpy, revenue_jpy, ebay_fees_jpy, profit_jpy, profit_rate, fx_rate, computed_at
    """
    rows: list[dict[str, Any]] = []
    for source, table, title_col, price_col, url_col in (
        ("mercari", "listings_mercari", "title", "price_jpy", "listing_url"),
        ("snkrdunk", "listings_snkrdunk", "product_name", "min_price_jpy", "product_url"),
    ):
        sql = f"""
        SELECT m.*, c.category, c.name_ja AS card_name, c.name_en, c.set_code,
               c.card_number, c.psa_grade,
               l.{title_col} AS title, l.{price_col} AS buy_price_jpy,
               l.{url_col} AS listing_url, l.image_url AS image_url
        FROM matches m
        JOIN cards c ON c.id = m.card_id
        JOIN {table} l ON l.id = m.source_listing_id
        WHERE m.source = ?
        """
        params: list[Any] = [source]
        if source == "mercari":
            sql += " AND l.active = 1"
        if exclude_ignored:
            sql += f" AND l.{url_col} NOT IN (SELECT listing_url FROM ignore_list)"
        if min_profit_rate is not None:
            sql += " AND m.profit_rate >= ?"
            params.append(min_profit_rate)
        if min_profit_jpy is not None:
            sql += " AND m.profit_jpy >= ?"
            params.append(min_profit_jpy)
        if confidences:
            sql += f" AND m.confidence IN ({','.join('?' for _ in confidences)})"
            params.extend(confidences)
        if psa_only:
            sql += " AND c.psa_grade IS NOT NULL"
        if category:
            sql += " AND c.category = ?"
            params.append(category)
        if not include_low_reliability:
            sql += " AND m.reliability = 'ok'"
        for r in conn.execute(sql, params).fetchall():
            rows.append(dict(r))
    rows.sort(key=lambda r: r["profit_rate"], reverse=True)
    return rows


# ------------------------------------------------- ignore / notified

def add_ignore(conn: sqlite3.Connection, source: str, listing_url: str, note: str = "") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO ignore_list (source, listing_url, note, created_at) VALUES (?, ?, ?, ?)",
        (source, listing_url, note, utcnow()),
    )


def is_ignored(conn: sqlite3.Connection, listing_url: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM ignore_list WHERE listing_url = ?", (listing_url,)
    ).fetchone()
    return row is not None


def remove_ignore(conn: sqlite3.Connection, listing_url: str) -> None:
    conn.execute("DELETE FROM ignore_list WHERE listing_url = ?", (listing_url,))


def list_ignored(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM ignore_list ORDER BY created_at DESC").fetchall()


def is_notified(conn: sqlite3.Connection, listing_url: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM notified_deals WHERE listing_url = ?", (listing_url,)
    ).fetchone()
    return row is not None


def mark_notified(conn: sqlite3.Connection, source: str, listing_url: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO notified_deals (source, listing_url, notified_at) VALUES (?, ?, ?)",
        (source, listing_url, utcnow()),
    )


# ------------------------------------------------------------ fx_rates

def save_fx_rate(conn: sqlite3.Connection, pair: str, rate: float) -> None:
    conn.execute(
        "INSERT INTO fx_rates (pair, rate, fetched_at) VALUES (?, ?, ?)",
        (pair, rate, utcnow()),
    )


def latest_fx_rate(conn: sqlite3.Connection, pair: str = "USDJPY") -> Optional[float]:
    row = conn.execute(
        "SELECT rate FROM fx_rates WHERE pair = ? ORDER BY fetched_at DESC LIMIT 1", (pair,)
    ).fetchone()
    return float(row["rate"]) if row else None


# --------------------------------------------------------- scrape_runs

def ebay_query_usage(conn: sqlite3.Connection) -> tuple[int, int]:
    """eBay 検索クエリの消費数 (本日UTC, 累計) を scrape_runs から集計する。

    本日分は「1日 max_ebay_queries_per_day 件」の上限管理に、累計は watchlist が
    上限より多いときのローテーション(毎回同じ先頭50枚に偏らないための開始位置)に使う。
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN started_at >= ? THEN queries_total ELSE 0 END), 0) AS today,
            COALESCE(SUM(queries_total), 0) AS total
        FROM scrape_runs WHERE source = 'ebay'
        """,
        (today,),
    ).fetchone()
    return int(row["today"]), int(row["total"])


def start_scrape_run(conn: sqlite3.Connection, source: str) -> int:
    cur = conn.execute(
        "INSERT INTO scrape_runs (source, started_at) VALUES (?, ?)", (source, utcnow())
    )
    return int(cur.lastrowid)


def finish_scrape_run(
    conn: sqlite3.Connection,
    run_id: int,
    queries_total: int,
    queries_failed: int,
    items_found: int,
    parse_failures: int,
    notes: str = "",
) -> None:
    conn.execute(
        """
        UPDATE scrape_runs
        SET finished_at = ?, queries_total = ?, queries_failed = ?,
            items_found = ?, parse_failures = ?, notes = ?
        WHERE id = ?
        """,
        (utcnow(), queries_total, queries_failed, items_found, parse_failures, notes, run_id),
    )
