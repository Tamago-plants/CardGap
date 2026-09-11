"""メルカリ完結フェーズ(SOLD収集・メルカリ内相場・割安検出)のテスト。

対象:
  - db.upsert_mercari_sold / mercari_sold_for_card(first_seen_at 保持・最良マッチ勝ち)
  - profit.profit_for_mercari_market(円建て損益の固定値)
  - pipeline.recompute_matches の相場選択(market.source: auto / ebay / mercari)
  - export の新フィールド(market_*, mercari_points, mercari_movers, 売れ筋)
  - notify._digest_mercari_embed(データ無しなら None)

DB は :memory:、ネットワークには一切出ない。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from cardgap import db, export, notify, pipeline
from cardgap.config import Config
from cardgap.models import (
    CONF_HIGH,
    CONF_NONE,
    Card,
    EbaySoldListing,
    MercariListing,
)
from cardgap.profit import profit_for_mercari_market

SOLD_URL = "https://jp.mercari.com/item/sold001"


# -------------------------------------------------------------------- fixtures

@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


def _cfg(market_source: str = "auto") -> Config:
    """recompute_matches / export / profit が参照するキー一式(ファイル非依存)。"""
    return Config(
        {
            "fx": {"conversion_margin": 0.02},
            "ebay_fees": {
                "final_value_fee": 0.1325,
                "per_order_fee_usd": 0.30,
                "international_fee": 0.0135,
                "promoted_listing": 0.02,
            },
            "shipping": {"default_out_jpy": 2500},
            "buy_side": {
                "mercari_fee_rate": 0.0,
                "mercari_shipping_jpy": 0,
                "snkrdunk_buyer_fee_rate": 0.055,
                "snkrdunk_shipping_jpy": 1000,
            },
            "threshold": {
                "min_profit_jpy": 5000,
                "min_profit_rate": 0.20,
                "min_sold_count_30d": 3,
            },
            "scrape": {"ebay_lookback_days": 30},
            "market": {"source": market_source},
            "mercari_sell": {"fee_rate": 0.10, "shipping_jpy": 210},
            "export": {"history_days": 90, "top_n": 10, "movers_n": 5},
        }
    )


def _day(offset: int) -> str:
    return (date.today() - timedelta(days=offset)).isoformat()


def _card(name_ja: str = "うずまきナルト", number: str = "忍-001") -> Card:
    return Card(
        category="naruto",
        name_ja=name_ja,
        name_en="Naruto Uzumaki",
        set_code=None,
        card_number=number,
        psa_grade=None,
    )


def _sold(
    url: str,
    price: int = 3000,
    card_id: int | None = None,
    conf: str = CONF_HIGH,
) -> MercariListing:
    return MercariListing(
        title="NARUTO カード 忍-001",
        price_jpy=price,
        condition=None,
        image_url="https://img.example/s.jpg",
        listing_url=url,
        card_id=card_id,
        match_confidence=conf,
    )


def _seed_card_with_solds(
    conn, prices: tuple[int, ...] = (2800, 3000, 3200)
) -> Card:
    """カード1枚 + 高confidenceのSOLD出品を prices 分投入する。"""
    card = _card()
    card.id = db.upsert_card(conn, card)
    db.upsert_mercari_sold(
        conn,
        [
            _sold(f"https://jp.mercari.com/item/sold{i:03d}", p, card.id)
            for i, p in enumerate(prices)
        ],
    )
    return card


def _add_active_listing(conn, card: Card, price: int = 1500) -> None:
    """買い側(販売中)の出品を1件登録する。"""
    db.upsert_mercari(
        conn,
        [
            MercariListing(
                title=f"{card.name_ja} 出品中",
                price_jpy=price,
                condition=None,
                image_url="https://img.example/b.jpg",
                listing_url="https://jp.mercari.com/item/active01",
                card_id=card.id,
                match_confidence=CONF_HIGH,
            )
        ],
    )


def _add_ebay_solds(conn, card: Card, prices_usd: tuple[float, ...] = (95.0, 100.0, 105.0)) -> None:
    db.insert_ebay_sold(
        conn,
        [
            EbaySoldListing(
                title="Naruto card 忍-001",
                price_usd=p,
                shipping_usd=0.0,
                sold_at=_day(1),
                image_url=None,
                listing_url=f"https://www.ebay.com/itm/{i}",
                card_id=card.id,
                match_confidence=CONF_HIGH,
            )
            for i, p in enumerate(prices_usd)
        ],
    )


# ------------------------------------------------------- upsert_mercari_sold

def test_upsert_mercari_sold_preserves_first_seen_at(conn):
    card = _card()
    card.id = db.upsert_card(conn, card)
    db.upsert_mercari_sold(conn, [_sold(SOLD_URL, 3000, card.id)])
    # 初観測日時を過去に書き換えてから再観測 → first_seen_at は初回値のまま
    conn.execute(
        "UPDATE listings_mercari_sold SET first_seen_at = ?, scraped_at = ?",
        ("2026-09-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
    )
    db.upsert_mercari_sold(conn, [_sold(SOLD_URL, 3000, card.id)])
    row = conn.execute(
        "SELECT first_seen_at, scraped_at FROM listings_mercari_sold WHERE listing_url = ?",
        (SOLD_URL,),
    ).fetchone()
    assert row["first_seen_at"] == "2026-09-01T00:00:00+00:00"
    assert row["scraped_at"] > "2026-09-01T00:00:00+00:00"  # 再観測で更新される
    assert conn.execute("SELECT COUNT(*) c FROM listings_mercari_sold").fetchone()["c"] == 1


def test_upsert_mercari_sold_better_match_wins(conn):
    card = _card()
    card.id = db.upsert_card(conn, card)
    # none で観測 → high 判定が来たら card_id/confidence が付け替わる
    db.upsert_mercari_sold(conn, [_sold(SOLD_URL, 3000, None, CONF_NONE)])
    db.upsert_mercari_sold(conn, [_sold(SOLD_URL, 3000, card.id, CONF_HIGH)])
    row = conn.execute(
        "SELECT card_id, match_confidence FROM listings_mercari_sold WHERE listing_url = ?",
        (SOLD_URL,),
    ).fetchone()
    assert row["card_id"] == card.id
    assert row["match_confidence"] == CONF_HIGH
    # 逆方向(high → none)には降格しない
    db.upsert_mercari_sold(conn, [_sold(SOLD_URL, 3000, None, CONF_NONE)])
    row = conn.execute(
        "SELECT card_id, match_confidence FROM listings_mercari_sold WHERE listing_url = ?",
        (SOLD_URL,),
    ).fetchone()
    assert row["card_id"] == card.id
    assert row["match_confidence"] == CONF_HIGH


def test_mercari_sold_for_card_filters_confidence_and_since(conn):
    card = _seed_card_with_solds(conn)  # high × 3
    db.upsert_mercari_sold(
        conn, [_sold("https://jp.mercari.com/item/noise", 9999, None, CONF_NONE)]
    )
    rows = db.mercari_sold_for_card(conn, card.id, _day(30))
    assert [r["price_jpy"] for r in rows] and len(rows) == 3
    # 未来を since にすると 0 件
    assert db.mercari_sold_for_card(conn, card.id, "2999-01-01") == []


# --------------------------------------------------- profit_for_mercari_market

def test_profit_for_mercari_market_golden_numbers():
    """中央値3000円・仕入1500円: 手数料300 + 送料210 → 利益990 / 率66%。"""
    p = profit_for_mercari_market(_cfg(), "mercari", 3000.0, 1500.0)
    assert p.revenue_jpy == pytest.approx(3000.0)
    assert p.ebay_fees_jpy == pytest.approx(300.0)  # 10%(列名は流用)
    assert p.ship_out_jpy == pytest.approx(210.0)
    assert p.buy_total_jpy == pytest.approx(1500.0)
    assert p.profit_jpy == pytest.approx(990.0)
    assert p.profit_rate == pytest.approx(0.66)
    assert p.fx_rate == pytest.approx(1.0)  # 為替は関与しない


def test_profit_for_mercari_market_snkrdunk_buy_fees():
    """スニダン仕入は購入手数料5.5% + 送料1000円が仕入総額に乗る。"""
    p = profit_for_mercari_market(_cfg(), "snkrdunk", 10000.0, 5000.0)
    assert p.buy_total_jpy == pytest.approx(5000 * 1.055 + 1000)  # 6275
    assert p.profit_jpy == pytest.approx(10000 - 1000 - 210 - 6275)  # 2515


# ------------------------------------------- recompute_matches: 相場の選択

def test_recompute_auto_falls_back_to_mercari(conn):
    """eBay相場が無い → auto はメルカリ売却相場(円)で割安検出する。"""
    card = _seed_card_with_solds(conn, (2800, 3000, 3200))
    _add_active_listing(conn, card, 1500)
    deals = pipeline.recompute_matches(_cfg("auto"), conn, fx_rate=150.0)
    assert len(deals) == 1
    d = deals[0]
    assert d.market_source == "mercari"
    assert d.stats.median_usd == pytest.approx(3000.0)  # 円の中央値が入る
    assert d.profit.profit_jpy == pytest.approx(990.0)
    assert d.profit.fx_rate == pytest.approx(1.0)
    # 日次スナップショットも書かれる
    snaps = db.mercari_market_history_for_card(conn, card.id)
    assert len(snaps) == 1
    assert snaps[0]["median_jpy"] == pytest.approx(3000.0)
    assert snaps[0]["count"] == 3
    # matches テーブルにも market_source が保存される
    row = conn.execute("SELECT market_source FROM matches").fetchone()
    assert row["market_source"] == "mercari"


def test_recompute_auto_prefers_ebay_when_available(conn):
    card = _seed_card_with_solds(conn)
    _add_active_listing(conn, card, 1500)
    _add_ebay_solds(conn, card)
    deals = pipeline.recompute_matches(_cfg("auto"), conn, fx_rate=150.0)
    assert len(deals) == 1
    assert deals[0].market_source == "ebay"
    assert deals[0].stats.median_usd == pytest.approx(100.0)  # USD 中央値
    assert deals[0].profit.fx_rate == pytest.approx(150.0)


def test_recompute_mode_mercari_forces_mercari(conn):
    card = _seed_card_with_solds(conn)
    _add_active_listing(conn, card, 1500)
    _add_ebay_solds(conn, card)
    deals = pipeline.recompute_matches(_cfg("mercari"), conn, fx_rate=150.0)
    assert len(deals) == 1
    assert deals[0].market_source == "mercari"
    assert deals[0].stats.median_usd == pytest.approx(3000.0)


def test_recompute_mode_ebay_without_ebay_data_yields_no_deals(conn):
    card = _seed_card_with_solds(conn)
    _add_active_listing(conn, card, 1500)
    deals = pipeline.recompute_matches(_cfg("ebay"), conn, fx_rate=150.0)
    assert deals == []
    # 相場スナップショット自体は蓄積される(騰落・売れ筋の元データ)
    assert len(db.mercari_market_history_for_card(conn, card.id)) == 1


# ------------------------------------------------------------------- export

def test_deals_payload_carries_market_fields(conn):
    card = _seed_card_with_solds(conn)
    _add_active_listing(conn, card, 1500)
    pipeline.recompute_matches(_cfg("auto"), conn, fx_rate=150.0)
    payload = export.build_deals_payload(_cfg(), conn)
    d = payload["deals"][0]
    assert d["market_source"] == "mercari"
    assert d["market_currency"] == "JPY"
    assert d["market_median"] == pytest.approx(3000.0)
    assert d["market_count"] == 3


def test_history_payload_includes_mercari_points(conn):
    card = _card()
    card.id = db.upsert_card(conn, card)
    db.upsert_mercari_market_snapshot(conn, card.id, _day(1), 3000.0, 5, 2500.0, 3500.0)
    db.upsert_mercari_market_snapshot(conn, card.id, _day(0), 3300.0, 6, 2600.0, 3900.0)
    payload = export.build_history_payload(_cfg(), conn)
    assert len(payload["cards"]) == 1  # eBay履歴が無くてもメルカリ履歴があれば載る
    c = payload["cards"][0]
    assert c["points"] == []
    assert [p["median_jpy"] for p in c["mercari_points"]] == [3000.0, 3300.0]  # 日付昇順
    assert c["mercari_points"][1]["count"] == 6
    assert c["mercari_points"][1]["min_jpy"] == pytest.approx(2600.0)
    assert c["mercari_points"][1]["max_jpy"] == pytest.approx(3900.0)


def test_summary_mercari_movers_and_top_selling(conn):
    up = _card("うずまきナルト", "忍-001")
    up.id = db.upsert_card(conn, up)
    down = _card("うちはサスケ", "忍-002")
    down.id = db.upsert_card(conn, down)
    # 騰落: up +10% / down -20%。売れ筋: down の方が件数多
    db.upsert_mercari_market_snapshot(conn, up.id, _day(1), 3000.0, 4, 2500.0, 3500.0)
    db.upsert_mercari_market_snapshot(conn, up.id, _day(0), 3300.0, 5, 2600.0, 3900.0)
    db.upsert_mercari_market_snapshot(conn, down.id, _day(1), 1000.0, 7, 900.0, 1100.0)
    db.upsert_mercari_market_snapshot(conn, down.id, _day(0), 800.0, 8, 700.0, 900.0)
    summary = export.build_summary_payload(_cfg(), conn)

    assert summary["market_mode"] == "auto"
    assert len(summary["mercari_movers_up"]) == 1
    m = summary["mercari_movers_up"][0]
    assert m["card_id"] == up.id
    assert m["median_jpy"] == pytest.approx(3300.0)
    assert m["prev_median_jpy"] == pytest.approx(3000.0)
    assert m["change_rate"] == pytest.approx(0.1)
    assert summary["mercari_movers_down"][0]["change_rate"] == pytest.approx(-0.2)

    top = summary["mercari_top_selling"]
    assert [t["card_id"] for t in top] == [down.id, up.id]  # 件数降順
    assert top[0]["count"] == 8 and top[0]["median_jpy"] == pytest.approx(800.0)

    ms = summary["profit_model"]["mercari_sell"]
    assert ms == {"fee_rate": 0.10, "shipping_jpy": 210.0}


def test_summary_mercari_movers_skip_stale_prev(conn):
    """前回スナップショットが8日超前なら騰落に載せない(休止明けの見かけ急変防止)。"""
    card = _card()
    card.id = db.upsert_card(conn, card)
    db.upsert_mercari_market_snapshot(conn, card.id, _day(20), 1000.0, 4, 900.0, 1100.0)
    db.upsert_mercari_market_snapshot(conn, card.id, _day(0), 3000.0, 5, 2500.0, 3500.0)
    summary = export.build_summary_payload(_cfg(), conn)
    assert summary["mercari_movers_up"] == []
    # 売れ筋には最新スナップショットとして載る
    assert summary["mercari_top_selling"][0]["card_id"] == card.id


# ------------------------------------------------------------------- digest

def test_digest_mercari_embed_none_when_empty():
    assert notify._digest_mercari_embed({}) is None
    assert (
        notify._digest_mercari_embed(
            {"mercari_movers_up": [], "mercari_movers_down": [], "mercari_top_selling": []}
        )
        is None
    )


def test_digest_mercari_embed_contents():
    summary = {
        "mercari_movers_up": [
            {"display_name": "忍-001", "prev_median_jpy": 3000.0, "median_jpy": 3300.0,
             "change_rate": 0.1}
        ],
        "mercari_movers_down": [
            {"display_name": "忍-002", "prev_median_jpy": 1000.0, "median_jpy": 800.0,
             "change_rate": -0.2}
        ],
        "mercari_top_selling": [
            {"display_name": "忍-002", "count": 8, "median_jpy": 800.0},
        ],
    }
    embed = notify._digest_mercari_embed(summary)
    assert embed is not None and embed["title"] == "メルカリ相場"
    desc = embed["description"]
    assert "📈 忍-001 ¥3,000 → ¥3,300 (+10.0%)" in desc
    assert "📉 忍-002 ¥1,000 → ¥800 (-20.0%)" in desc
    assert "1. 忍-002 8件 / 中央値¥800" in desc


def test_digest_drops_empty_ebay_movers_when_mercari_present():
    """eBay騰落が空でメルカリ相場がある場合、プレースホルダの「相場動向」を出さない。"""
    summary = {
        "date": "2026-09-11",
        "deal_count_total": 0,
        "deal_count_above_threshold": 0,
        "fx_rate": 150.0,
        "top_by_rate": [],
        "movers_up": [],
        "movers_down": [],
        "mercari_top_selling": [
            {"display_name": "忍-002", "count": 8, "median_jpy": 800.0},
        ],
    }
    titles = [e["title"] for e in notify.build_digest_messages(summary)[0]["embeds"]]
    assert titles == ["サマリ", "利益率ランキング TOP5", "メルカリ相場"]


def test_deal_embed_mercari_market_shows_yen():
    """メルカリ売却相場基準の案件は embed の相場欄が円表記になる。"""
    from cardgap.models import Deal, MarketStats, ProfitResult

    card = _card()
    card.id = 1
    deal = Deal(
        card=card,
        source="mercari",
        source_listing_id=1,
        title="NARUTO カード 忍-001",
        buy_price_jpy=1500,
        listing_url="https://jp.mercari.com/item/active01",
        image_url=None,
        confidence=CONF_HIGH,
        stats=MarketStats(median_usd=3000.0, count=3, min_usd=2800.0, max_usd=3200.0,
                          reliability="ok"),
        profit=ProfitResult(revenue_jpy=3000.0, ebay_fees_jpy=300.0, ship_out_jpy=210.0,
                            buy_total_jpy=1500.0, profit_jpy=990.0, profit_rate=0.66,
                            fx_rate=1.0),
        market_source="mercari",
    )
    embed = notify.build_deal_embed(deal)
    field = next(f for f in embed["fields"] if "中央値" in f["name"])
    assert field["name"] == "メルカリ売却中央値"
    assert field["value"] == "¥3,000 (3件)"
