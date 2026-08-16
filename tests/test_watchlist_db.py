"""watchlist CSV 読み込み(cardgap.watchlist)と DB 層(cardgap.db)のテスト。

DB は sqlite3 の ":memory:" を使い、ファイル・ネットワークに依存しない。
"""

from __future__ import annotations

import pytest

from cardgap import db
from cardgap.models import (
    CONF_HIGH,
    CONF_MEDIUM,
    RELIABILITY_LOW,
    RELIABILITY_OK,
    Card,
    Deal,
    EbaySoldListing,
    MarketStats,
    MercariListing,
    ProfitResult,
    SnkrdunkListing,
)
from cardgap.watchlist import load_watchlist_csv


# ------------------------------------------------------------------- watchlist

def test_load_watchlist_csv_japanese_headers(tmp_path):
    p = tmp_path / "watchlist.csv"
    p.write_text(
        "カテゴリ,日本語名,英語名,セット記号,カード番号,PSAグレード指定,有効フラグ\n"
        "pokemon,リザードンVSTAR,Charizard VSTAR,s12a,201/190,10,1\n"
        "naruto,うずまきナルト,Naruto Uzumaki,,25,,0\n",
        encoding="utf-8",
    )
    cards = load_watchlist_csv(p)
    assert len(cards) == 2

    a = cards[0]
    assert a.category == "pokemon"
    assert a.name_ja == "リザードンVSTAR"
    assert a.name_en == "Charizard VSTAR"
    assert a.set_code == "s12a"
    assert a.card_number == "201/190"
    assert a.psa_grade == 10
    assert a.enabled is True

    b = cards[1]
    assert b.category == "naruto"
    assert b.set_code is None       # 空欄 → None
    assert b.card_number == "25"
    assert b.psa_grade is None      # PSA空欄 = 生カード
    assert b.enabled is False       # 有効フラグ "0" → 無効


# -------------------------------------------------------------------- fixtures

@pytest.fixture()
def conn():
    """インメモリDB(connect がスキーマも作る)。"""
    c = db.connect(":memory:")
    yield c
    c.close()


def _card_a() -> Card:
    return Card(
        category="pokemon",
        name_ja="リザードン",
        name_en="Charizard",
        set_code="s12a",
        card_number="201/190",
        psa_grade=10,
    )


def _card_b() -> Card:
    return Card(
        category="naruto",
        name_ja="うずまきナルト",
        name_en="Naruto Uzumaki",
        set_code=None,
        card_number="25",
        psa_grade=None,
    )


def _stats(reliability: str = RELIABILITY_OK) -> MarketStats:
    return MarketStats(
        median_usd=100.0, count=5, min_usd=80.0, max_usd=120.0, reliability=reliability
    )


def _profit(rate: float) -> ProfitResult:
    return ProfitResult(
        revenue_jpy=14700.0,
        ebay_fees_jpy=2484.0,
        ship_out_jpy=2500.0,
        buy_total_jpy=5000.0,
        profit_jpy=4716.0,
        profit_rate=rate,
        fx_rate=150.0,
    )


def _mercari_listing_id(conn, url: str) -> int:
    row = conn.execute(
        "SELECT id FROM listings_mercari WHERE listing_url = ?", (url,)
    ).fetchone()
    return int(row["id"])


# -------------------------------------------------------------------------- db

def test_connect_creates_schema(conn):
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "cards",
        "listings_ebay_sold",
        "listings_mercari",
        "listings_snkrdunk",
        "matches",
        "fx_rates",
        "ignore_list",
        "notified_deals",
        "scrape_runs",
    } <= tables


def test_upsert_card_is_idempotent(conn):
    id1 = db.upsert_card(conn, _card_a())
    # 2回目は同じ id が返り、行は増えない(name_ja/enabled は更新される)
    card2 = _card_a()
    card2.name_ja = "リザードンex"
    id2 = db.upsert_card(conn, card2)
    assert id1 == id2
    assert conn.execute("SELECT COUNT(*) AS n FROM cards").fetchone()["n"] == 1
    assert db.get_card(conn, id1).name_ja == "リザードンex"


def test_insert_ebay_sold_ignores_duplicates(conn):
    def item(sold_at: str = "2026-08-01") -> EbaySoldListing:
        return EbaySoldListing(
            title="Charizard VSTAR 201/190 PSA 10",
            price_usd=450.0,
            shipping_usd=0.0,
            sold_at=sold_at,
            image_url=None,
            listing_url="https://www.ebay.com/itm/256011111111",
        )

    assert db.insert_ebay_sold(conn, [item()]) == 1
    # 同一 url + sold_at は無視される
    assert db.insert_ebay_sold(conn, [item()]) == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM listings_ebay_sold").fetchone()["n"] == 1
    # 同一 url でも sold_at が違えば別行(再出品扱い)
    assert db.insert_ebay_sold(conn, [item(sold_at="2026-08-05")]) == 1


def test_upsert_mercari_updates_price_for_same_url(conn):
    url = "https://jp.mercari.com/item/m111"

    def listing(price: int) -> MercariListing:
        return MercariListing(
            title="リザードン 201/190 PSA10",
            price_jpy=price,
            condition=None,
            image_url=None,
            listing_url=url,
            match_confidence=CONF_HIGH,
        )

    db.upsert_mercari(conn, [listing(10000)])
    db.upsert_mercari(conn, [listing(8800)])  # 値下げを検知して上書き
    rows = conn.execute("SELECT price_jpy, active FROM listings_mercari").fetchall()
    assert len(rows) == 1
    assert rows[0]["price_jpy"] == 8800
    assert rows[0]["active"] == 1


def test_deactivate_stale_mercari(conn):
    old_url = "https://jp.mercari.com/item/m_old"
    new_url = "https://jp.mercari.com/item/m_new"
    db.upsert_mercari(
        conn,
        [
            MercariListing(title="旧出品", price_jpy=1000, condition=None,
                           image_url=None, listing_url=old_url),
            MercariListing(title="新出品", price_jpy=2000, condition=None,
                           image_url=None, listing_url=new_url),
        ],
    )
    # 旧出品の scraped_at を過去に固定(前回実行分の想定)
    conn.execute(
        "UPDATE listings_mercari SET scraped_at = ? WHERE listing_url = ?",
        ("2020-01-01T00:00:00Z", old_url),
    )
    assert db.deactivate_stale_mercari(conn, "2021-01-01T00:00:00Z") == 1
    active = {
        r["listing_url"]: r["active"]
        for r in conn.execute("SELECT listing_url, active FROM listings_mercari")
    }
    assert active[old_url] == 0
    assert active[new_url] == 1
    # 再度見つかれば active に戻る
    db.upsert_mercari(
        conn,
        [MercariListing(title="旧出品", price_jpy=1000, condition=None,
                        image_url=None, listing_url=old_url)],
    )
    row = conn.execute(
        "SELECT active FROM listings_mercari WHERE listing_url = ?", (old_url,)
    ).fetchone()
    assert row["active"] == 1


# ---------------------------------------------- rebuild_matches + list_deals

def _setup_two_deals(conn) -> tuple[str, str]:
    """カード2枚 + メルカリ出品2件 + matches を作る。(URL_A, URL_B) を返す。

    A: pokemon / PSA10 / confidence=high / profit_rate=0.9 / reliability=ok
    B: naruto  / raw    / confidence=medium / profit_rate=0.3 / reliability=low
    """
    card_a = _card_a()
    card_a.id = db.upsert_card(conn, card_a)
    card_b = _card_b()
    card_b.id = db.upsert_card(conn, card_b)

    url_a = "https://jp.mercari.com/item/m111"
    url_b = "https://jp.mercari.com/item/m222"
    db.upsert_mercari(
        conn,
        [
            MercariListing(title="リザードン 201/190 PSA10", price_jpy=5000,
                           condition=None, image_url="https://img/a.jpg",
                           listing_url=url_a, card_id=card_a.id,
                           match_confidence=CONF_HIGH),
            MercariListing(title="うずまきナルト No.25", price_jpy=8000,
                           condition=None, image_url=None,
                           listing_url=url_b, card_id=card_b.id,
                           match_confidence=CONF_MEDIUM),
        ],
    )

    deals = [
        Deal(
            card=card_a, source="mercari",
            source_listing_id=_mercari_listing_id(conn, url_a),
            title="リザードン 201/190 PSA10", buy_price_jpy=5000,
            listing_url=url_a, image_url="https://img/a.jpg",
            confidence=CONF_HIGH, stats=_stats(), profit=_profit(0.9),
        ),
        Deal(
            card=card_b, source="mercari",
            source_listing_id=_mercari_listing_id(conn, url_b),
            title="うずまきナルト No.25", buy_price_jpy=8000,
            listing_url=url_b, image_url=None,
            confidence=CONF_MEDIUM, stats=_stats(RELIABILITY_LOW), profit=_profit(0.3),
        ),
    ]
    assert db.rebuild_matches(conn, deals) == 2
    return url_a, url_b


def test_rebuild_matches_and_list_deals_smoke(conn):
    url_a, _ = _setup_two_deals(conn)
    rows = db.list_deals(conn)
    assert len(rows) == 2
    # profit_rate 降順ソート → 先頭はカードA
    top = rows[0]
    assert top["card_name"] == "リザードン"
    assert top["name_en"] == "Charizard"
    assert top["category"] == "pokemon"
    assert top["set_code"] == "s12a"
    assert top["card_number"] == "201/190"
    assert top["psa_grade"] == 10
    assert top["source"] == "mercari"
    assert top["buy_price_jpy"] == 5000
    assert top["listing_url"] == url_a
    assert top["confidence"] == CONF_HIGH
    assert top["ebay_median_usd"] == pytest.approx(100.0)
    assert top["reliability"] == RELIABILITY_OK
    assert top["profit_jpy"] == pytest.approx(4716.0)
    assert top["profit_rate"] == pytest.approx(0.9)
    assert top["fx_rate"] == pytest.approx(150.0)


def test_list_deals_ignore_flow(conn):
    url_a, url_b = _setup_two_deals(conn)
    db.add_ignore(conn, "mercari", url_a, note="偽物疑い")
    assert db.is_ignored(conn, url_a)
    rows = db.list_deals(conn)
    assert [r["listing_url"] for r in rows] == [url_b]  # 無視した出品は消える
    # exclude_ignored=False なら見える
    assert len(db.list_deals(conn, exclude_ignored=False)) == 2
    db.remove_ignore(conn, url_a)
    assert not db.is_ignored(conn, url_a)
    assert len(db.list_deals(conn)) == 2


def test_list_deals_psa_only_filter(conn):
    url_a, _ = _setup_two_deals(conn)
    rows = db.list_deals(conn, psa_only=True)
    assert [r["listing_url"] for r in rows] == [url_a]  # PSA指定カードのみ


def test_list_deals_category_filter(conn):
    _, url_b = _setup_two_deals(conn)
    rows = db.list_deals(conn, category="naruto")
    assert [r["listing_url"] for r in rows] == [url_b]


def test_list_deals_confidences_filter(conn):
    url_a, _ = _setup_two_deals(conn)
    rows = db.list_deals(conn, confidences=(CONF_HIGH,))
    assert [r["listing_url"] for r in rows] == [url_a]


def test_list_deals_reliability_and_threshold_filters(conn):
    url_a, _ = _setup_two_deals(conn)
    # B は reliability=low なので除外される
    rows = db.list_deals(conn, include_low_reliability=False)
    assert [r["listing_url"] for r in rows] == [url_a]
    # 利益率の下限フィルタ
    rows = db.list_deals(conn, min_profit_rate=0.5)
    assert [r["listing_url"] for r in rows] == [url_a]


# ------------------------------------------------ レビューで発見したバグの回帰テスト

def _twin_cards(conn):
    """同一カードの raw / PSA10 指定の2枚(watchlist の典型パターン)。"""
    base = dict(
        category="pokemon", name_ja="リザードンex", name_en="Charizard ex",
        set_code="sv2a", card_number="201/165",
    )
    raw = Card(**base, psa_grade=None)
    psa = Card(**base, psa_grade=10)
    raw.id = db.upsert_card(conn, raw)
    psa.id = db.upsert_card(conn, psa)
    return raw, psa


def test_ebay_ranked_upsert_high_reclaims_none_row(conn):
    """同一落札が複数カードのクエリに現れても、confidence の高い判定が行を取る。

    先勝ちの INSERT OR IGNORE だと raw カードの 'none' 判定が枠を占有し、
    PSA10 指定カードの相場が恒久的に 0 件になる(レビュー指摘の回帰)。
    """
    raw, psa = _twin_cards(conn)
    url = "https://www.ebay.com/itm/256099999999"
    common = dict(
        title="Charizard ex sv2a 201/165 PSA 10", price_usd=450.0,
        shipping_usd=0.0, sold_at="2026-08-10", image_url=None, listing_url=url,
    )
    # raw カードのクエリが先に 'none' で挿入
    db.insert_ebay_sold(conn, [EbaySoldListing(**common, card_id=raw.id, match_confidence="none")])
    # 後から PSA カードのクエリが 'high' で来たら行を取り直せる
    db.insert_ebay_sold(conn, [EbaySoldListing(**common, card_id=psa.id, match_confidence="high")])
    rows = conn.execute("SELECT * FROM listings_ebay_sold").fetchall()
    assert len(rows) == 1
    assert rows[0]["card_id"] == psa.id
    assert rows[0]["match_confidence"] == "high"
    # 逆方向: 'none' が 'high' を潰すことはない
    db.insert_ebay_sold(conn, [EbaySoldListing(**common, card_id=raw.id, match_confidence="none")])
    row = conn.execute("SELECT * FROM listings_ebay_sold").fetchone()
    assert row["card_id"] == psa.id and row["match_confidence"] == "high"
    assert len(db.ebay_sold_for_card(conn, psa.id, "2026-01-01")) == 1


def test_mercari_upsert_confidence_not_downgraded_by_other_card(conn):
    """別カードのクエリ結果に混ざった同一出品が、既存の high マッチを壊さない。"""
    raw, psa = _twin_cards(conn)
    url = "https://jp.mercari.com/item/m99999999999"

    def listing(card_id, conf):
        return MercariListing(
            title="リザードンex sv2a 201/165 PSA10", price_jpy=50000,
            condition=None, image_url=None, listing_url=url,
            card_id=card_id, match_confidence=conf,
        )

    db.upsert_mercari(conn, [listing(psa.id, "high")])
    db.upsert_mercari(conn, [listing(raw.id, "none")])  # 別カードの none は無視される
    row = conn.execute("SELECT * FROM listings_mercari").fetchone()
    assert row["card_id"] == psa.id
    assert row["match_confidence"] == "high"
    # 価格・scraped_at・active は無条件更新される
    db.upsert_mercari(conn, [MercariListing(
        title="リザードンex sv2a 201/165 PSA10", price_jpy=48000,
        condition=None, image_url=None, listing_url=url,
        card_id=raw.id, match_confidence="none",
    )])
    row = conn.execute("SELECT * FROM listings_mercari").fetchone()
    assert row["price_jpy"] == 48000 and row["card_id"] == psa.id
    # 同一カードの再スクレイプなら自分の最新判定で上書きできる(格下げも可)
    db.upsert_mercari(conn, [listing(psa.id, "none")])
    row = conn.execute("SELECT * FROM listings_mercari").fetchone()
    assert row["card_id"] == psa.id and row["match_confidence"] == "none"


def test_snkrdunk_upsert_confidence_not_downgraded_by_other_card(conn):
    raw, psa = _twin_cards(conn)
    url = "https://snkrdunk.com/trading-cards/99999"

    def listing(card_id, conf):
        return SnkrdunkListing(
            product_name="リザードンex sv2a 201/165 PSA10", min_price_jpy=60000,
            product_url=url, card_id=card_id, match_confidence=conf,
        )

    db.upsert_snkrdunk(conn, [listing(psa.id, "high")])
    db.upsert_snkrdunk(conn, [listing(raw.id, "none")])
    row = conn.execute("SELECT * FROM listings_snkrdunk").fetchone()
    assert row["card_id"] == psa.id and row["match_confidence"] == "high"


def test_deactivate_stale_mercari_excludes_failed_cards(conn):
    """クエリ失敗カードの出品は「見えなかった」だけなので売切れ扱いにしない。"""
    raw, psa = _twin_cards(conn)
    for card, url in ((raw, "https://jp.mercari.com/item/mAAA"), (psa, "https://jp.mercari.com/item/mBBB")):
        db.upsert_mercari(conn, [MercariListing(
            title="t", price_jpy=1000, condition=None, image_url=None,
            listing_url=url, card_id=card.id, match_confidence="high",
        )])
    conn.execute("UPDATE listings_mercari SET scraped_at = '2000-01-01T00:00:00Z'")
    n = db.deactivate_stale_mercari(
        conn, "2001-01-01T00:00:00Z", exclude_card_ids=[raw.id]
    )
    assert n == 1
    rows = {r["listing_url"]: r["active"] for r in conn.execute("SELECT * FROM listings_mercari")}
    assert rows["https://jp.mercari.com/item/mAAA"] == 1  # 失敗カード → 維持
    assert rows["https://jp.mercari.com/item/mBBB"] == 0  # 正常カード → 売切れ扱い


def test_ebay_query_usage(conn):
    assert db.ebay_query_usage(conn) == (0, 0)
    run_id = db.start_scrape_run(conn, "ebay")
    db.finish_scrape_run(conn, run_id, queries_total=50, queries_failed=0,
                         items_found=100, parse_failures=0)
    today, total = db.ebay_query_usage(conn)
    assert today == 50 and total == 50
    # 過去日の実行は「本日」には数えず累計にのみ入る
    conn.execute("UPDATE scrape_runs SET started_at = '2000-01-01T00:00:00Z'")
    today, total = db.ebay_query_usage(conn)
    assert today == 0 and total == 50
