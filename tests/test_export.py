"""サイト用JSONエクスポート(cardgap.export)と db の market_history 系のテスト。

DB は sqlite3 の ":memory:" を使い、ファイル出力は tmp_path のみ。
ネットワークには一切出ない。

market_history の日付は「今日」からの相対で投入する
(build_history_payload の since が date.today() 基準のため)。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest

from cardgap import db, export
from cardgap.config import Config
from cardgap.models import (
    CONF_HIGH,
    CONF_LOW,
    RELIABILITY_LOW,
    RELIABILITY_OK,
    Card,
    Deal,
    MarketStats,
    MercariListing,
    ProfitResult,
)

URL_A = "https://jp.mercari.com/item/m111"


# -------------------------------------------------------------------- fixtures

@pytest.fixture()
def conn():
    """インメモリDB(connect がスキーマも作る)。"""
    c = db.connect(":memory:")
    yield c
    c.close()


def _cfg() -> Config:
    """config.yaml と同じ構造の dict から直接構築(ファイル非依存)。"""
    return Config(
        {
            "threshold": {
                "min_profit_jpy": 5000,
                "min_profit_rate": 0.20,
                "min_sold_count_30d": 3,
            },
            "export": {
                "output_dir": "site/public/data",
                "history_days": 90,
                "top_n": 10,
                "movers_n": 5,
            },
        }
    )


def _day(offset: int) -> str:
    """今日から offset 日前の ISO 日付。"""
    return (date.today() - timedelta(days=offset)).isoformat()


def _card_raw() -> Card:
    """pokemon 生カード(相場は上昇させる)。"""
    return Card(
        category="pokemon",
        name_ja="ピカチュウ",
        name_en="Pikachu",
        set_code="s8b",
        card_number="001/100",
        psa_grade=None,
    )


def _card_psa() -> Card:
    """pokemon PSA10 カード(相場は下落させる)。"""
    return Card(
        category="pokemon",
        name_ja="リザードン",
        name_en="Charizard",
        set_code="s12a",
        card_number="201/190",
        psa_grade=10,
    )


def _seed_cards_and_history(conn) -> tuple[Card, Card]:
    """カード2枚を upsert し、market_history を2日分ずつ投入する。

    raw: 100 → 110 USD(+10%) / psa: 50 → 40 USD(-20%)。
    ORDER BY 依存を検出できるよう、わざと新しい日付から先に insert する。
    """
    raw = _card_raw()
    raw.id = db.upsert_card(conn, raw)
    psa = _card_psa()
    psa.id = db.upsert_card(conn, psa)

    db.upsert_market_snapshot(conn, raw.id, _day(0), 110.0, 6, 95.0, 130.0, fx_rate=151.0)
    db.upsert_market_snapshot(conn, raw.id, _day(1), 100.0, 5, 90.0, 120.0, fx_rate=150.0)
    db.upsert_market_snapshot(conn, psa.id, _day(0), 40.0, 3, 35.0, 55.0)
    db.upsert_market_snapshot(conn, psa.id, _day(1), 50.0, 4, 45.0, 60.0)
    return raw, psa


def _stats(reliability: str = RELIABILITY_OK) -> MarketStats:
    return MarketStats(
        median_usd=100.0, count=5, min_usd=80.0, max_usd=120.0, reliability=reliability
    )


def _profit(profit_jpy: float, profit_rate: float) -> ProfitResult:
    return ProfitResult(
        revenue_jpy=15000.0,
        ebay_fees_jpy=2000.0,
        ship_out_jpy=2500.0,
        buy_total_jpy=5000.0,
        profit_jpy=profit_jpy,
        profit_rate=profit_rate,
        fx_rate=150.0,
    )


def _make_mercari_deal(
    conn,
    card: Card,
    url: str,
    *,
    buy_price_jpy: int = 5000,
    confidence: str = CONF_HIGH,
    reliability: str = RELIABILITY_OK,
    profit_jpy: float = 8000.0,
    profit_rate: float = 0.4,
) -> Deal:
    """メルカリ出品1件を登録し、それを指す Deal(models 直組み立て)を返す。

    rebuild_matches に渡すのは呼び出し側。
    """
    title = f"{card.name_ja} 出品"
    db.upsert_mercari(
        conn,
        [
            MercariListing(
                title=title,
                price_jpy=buy_price_jpy,
                condition=None,
                image_url="https://img.example/a.jpg",
                listing_url=url,
                card_id=card.id,
                match_confidence=confidence,
            )
        ],
    )
    listing_id = int(
        conn.execute(
            "SELECT id FROM listings_mercari WHERE listing_url = ?", (url,)
        ).fetchone()["id"]
    )
    return Deal(
        card=card,
        source="mercari",
        source_listing_id=listing_id,
        title=title,
        buy_price_jpy=buy_price_jpy,
        listing_url=url,
        image_url="https://img.example/a.jpg",
        confidence=confidence,
        stats=_stats(reliability),
        profit=_profit(profit_jpy, profit_rate),
    )


# --------------------------------------------------------- build_deals_payload

def test_build_deals_payload_single_deal_keys(conn):
    _, psa = _seed_cards_and_history(conn)
    deal = _make_mercari_deal(conn, psa, URL_A, buy_price_jpy=5000, profit_rate=0.4)
    assert db.rebuild_matches(conn, [deal]) == 1

    payload = export.build_deals_payload(_cfg(), conn)
    assert "generated_at" in payload
    assert len(payload["deals"]) == 1

    d = payload["deals"][0]
    # 表示名は 日本語名 + 番号 + セット + PSA
    assert d["display_name"] == "リザードン 201/190 s12a PSA10"
    assert d["card_id"] == psa.id
    assert d["category"] == "pokemon"
    assert d["name_ja"] == "リザードン"
    assert d["name_en"] == "Charizard"
    assert d["set_code"] == "s12a"
    assert d["card_number"] == "201/190"
    assert d["psa_grade"] == 10
    assert d["source"] == "mercari"
    assert d["title"] == "リザードン 出品"
    assert d["buy_price_jpy"] == 5000
    assert d["listing_url"] == URL_A
    assert d["image_url"] == "https://img.example/a.jpg"
    assert d["confidence"] == CONF_HIGH
    assert d["reliability"] == RELIABILITY_OK
    assert d["ebay_median_usd"] == pytest.approx(100.0)
    assert d["ebay_count_30d"] == 5
    assert d["ebay_min_usd"] == pytest.approx(80.0)
    assert d["ebay_max_usd"] == pytest.approx(120.0)
    assert d["buy_total_jpy"] == pytest.approx(5000.0)
    assert d["revenue_jpy"] == pytest.approx(15000.0)
    assert d["ebay_fees_jpy"] == pytest.approx(2000.0)
    assert d["profit_jpy"] == pytest.approx(8000.0)
    assert d["profit_rate"] == pytest.approx(0.4)
    assert d["fx_rate"] == pytest.approx(150.0)
    assert isinstance(d["computed_at"], str) and d["computed_at"]


# ------------------------------------------------------- build_history_payload

def test_build_history_payload_two_cards_points_ascending(conn):
    raw, psa = _seed_cards_and_history(conn)
    payload = export.build_history_payload(Config({}), conn)

    assert "generated_at" in payload
    assert payload["days"] == 90  # 設定なしの既定値
    assert len(payload["cards"]) == 2

    by_id = {c["card_id"]: c for c in payload["cards"]}
    entry = by_id[raw.id]
    assert entry["display_name"] == "ピカチュウ 001/100 s8b"
    assert entry["category"] == "pokemon"
    assert entry["psa_grade"] is None
    # insert は新しい日付が先だが、points は日付昇順で返る
    assert [p["date"] for p in entry["points"]] == [_day(1), _day(0)]
    latest = entry["points"][-1]
    assert latest["median_usd"] == pytest.approx(110.0)
    assert latest["count"] == 6
    assert latest["min_usd"] == pytest.approx(95.0)
    assert latest["max_usd"] == pytest.approx(130.0)

    assert [p["date"] for p in by_id[psa.id]["points"]] == [_day(1), _day(0)]


def test_build_history_payload_history_days_config(conn):
    raw, _ = _seed_cards_and_history(conn)
    # 窓外(10日前)のスナップショットを追加
    db.upsert_market_snapshot(conn, raw.id, _day(10), 90.0, 2, 85.0, 95.0)
    # 窓外の履歴しか持たないカードは cards 自体から落ちる
    old_only = Card(
        category="pokemon", name_ja="ミュウ", name_en="Mew",
        set_code="s8b", card_number="002/100", psa_grade=None,
    )
    old_only.id = db.upsert_card(conn, old_only)
    db.upsert_market_snapshot(conn, old_only.id, _day(10), 30.0, 2, 25.0, 35.0)

    cfg = Config({"export": {"history_days": 5}})
    payload = export.build_history_payload(cfg, conn)
    assert payload["days"] == 5
    by_id = {c["card_id"]: c for c in payload["cards"]}
    assert old_only.id not in by_id
    # 10日前の点は窓(5日)の外なので落ちる
    assert [p["date"] for p in by_id[raw.id]["points"]] == [_day(1), _day(0)]

    # days 引数は設定より優先
    payload = export.build_history_payload(cfg, conn, days=90)
    assert payload["days"] == 90
    by_id = {c["card_id"]: c for c in payload["cards"]}
    assert len(by_id[raw.id]["points"]) == 3
    assert old_only.id in by_id


# ------------------------------------------------------------- _compute_movers

def test_compute_movers_requires_two_snapshots(conn):
    card = _card_raw()
    card.id = db.upsert_card(conn, card)
    db.upsert_market_snapshot(conn, card.id, _day(0), 100.0, 5, 90.0, 110.0)
    assert export._compute_movers(conn) == []  # 1日分では騰落を計算しない


def test_compute_movers_gap_boundary(conn):
    # 前回が9日前 → gap 9 > max_gap_days(8) なので除外
    stale = _card_raw()
    stale.id = db.upsert_card(conn, stale)
    db.upsert_market_snapshot(conn, stale.id, _day(9), 100.0, 5, 90.0, 110.0)
    db.upsert_market_snapshot(conn, stale.id, _day(0), 120.0, 5, 100.0, 130.0)
    # 前回がちょうど8日前 → 境界内なので含まれる
    fresh = _card_psa()
    fresh.id = db.upsert_card(conn, fresh)
    db.upsert_market_snapshot(conn, fresh.id, _day(8), 100.0, 5, 90.0, 110.0)
    db.upsert_market_snapshot(conn, fresh.id, _day(0), 90.0, 5, 80.0, 100.0)

    movers = export._compute_movers(conn, max_gap_days=8)
    assert [m["card_id"] for m in movers] == [fresh.id]
    assert movers[0]["change_rate"] == pytest.approx(-0.1)


# ------------------------------------------------------- build_summary_payload

def test_build_summary_payload_movers_change_rate(conn):
    raw, psa = _seed_cards_and_history(conn)
    db.save_fx_rate(conn, "USDJPY", 150.0)
    run_id = db.start_scrape_run(conn, "ebay")
    db.finish_scrape_run(conn, run_id, queries_total=10, queries_failed=1,
                         items_found=100, parse_failures=2)

    payload = export.build_summary_payload(_cfg(), conn)
    assert "generated_at" in payload
    assert payload["date"] == date.today().isoformat()
    assert payload["fx_rate"] == pytest.approx(150.0)
    assert payload["thresholds"] == {
        "min_profit_jpy": 5000.0,
        "min_profit_rate": 0.20,
        "min_sold_count_30d": 3,
    }

    # raw: (110-100)/100 = +0.1 / psa: (40-50)/50 = -0.2(手計算)
    up = payload["movers_up"]
    assert [m["card_id"] for m in up] == [raw.id]
    assert up[0]["change_rate"] == pytest.approx(0.1)
    assert up[0]["prev_median_usd"] == pytest.approx(100.0)
    assert up[0]["median_usd"] == pytest.approx(110.0)
    assert up[0]["date"] == _day(0)
    assert up[0]["prev_date"] == _day(1)
    assert up[0]["display_name"] == "ピカチュウ 001/100 s8b"

    down = payload["movers_down"]
    assert [m["card_id"] for m in down] == [psa.id]
    assert down[0]["change_rate"] == pytest.approx(-0.2)

    health = payload["scrape_health"]
    assert [h["source"] for h in health] == ["ebay"]
    assert health[0]["queries_total"] == 10
    assert health[0]["parse_failures"] == 2


def test_build_summary_payload_top_filtered_by_thresholds(conn):
    raw, psa = _seed_cards_and_history(conn)
    deals = [
        # 閾値超え(rate>=0.2 / profit>=5000 / ok / high)→ 唯一の残留
        _make_mercari_deal(conn, psa, "https://jp.mercari.com/item/m_ok",
                           profit_rate=0.5, profit_jpy=9000.0),
        # 利益率が閾値未満
        _make_mercari_deal(conn, raw, "https://jp.mercari.com/item/m_low_rate",
                           profit_rate=0.15, profit_jpy=9000.0),
        # 利益額が閾値未満
        _make_mercari_deal(conn, raw, "https://jp.mercari.com/item/m_low_jpy",
                           profit_rate=0.6, profit_jpy=3000.0),
        # 相場信頼度 low
        _make_mercari_deal(conn, psa, "https://jp.mercari.com/item/m_low_rel",
                           profit_rate=0.5, profit_jpy=9000.0,
                           reliability=RELIABILITY_LOW),
        # confidence low(high|medium のみ許可)
        _make_mercari_deal(conn, psa, "https://jp.mercari.com/item/m_low_conf",
                           profit_rate=0.45, profit_jpy=9000.0,
                           confidence=CONF_LOW),
    ]
    assert db.rebuild_matches(conn, deals) == 5

    payload = export.build_summary_payload(_cfg(), conn)
    assert payload["deal_count_total"] == 5
    assert payload["deal_count_above_threshold"] == 1
    assert [d["listing_url"] for d in payload["top_by_rate"]] == [
        "https://jp.mercari.com/item/m_ok"
    ]
    assert [d["listing_url"] for d in payload["top_by_profit"]] == [
        "https://jp.mercari.com/item/m_ok"
    ]
    assert payload["top_by_rate"][0]["profit_rate"] == pytest.approx(0.5)


# ------------------------------------------------------------ export_site_data

def test_export_site_data_writes_three_json_files(conn, tmp_path):
    _, psa = _seed_cards_and_history(conn)
    deal = _make_mercari_deal(conn, psa, URL_A)
    db.rebuild_matches(conn, [deal])

    written = export.export_site_data(_cfg(), conn, out_dir=tmp_path)
    assert [p.name for p in written] == ["deals.json", "history.json", "summary.json"]
    for path in written:
        assert path.parent == tmp_path
        assert path.exists()
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        assert "generated_at" in payload

    # 中身の軽い整合性チェック(サイト側が読む代表キー)
    deals = json.loads((tmp_path / "deals.json").read_text(encoding="utf-8"))
    assert len(deals["deals"]) == 1
    history = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert len(history["cards"]) == 2
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["deal_count_total"] == 1


# --------------------------------------------- db: market_history / scrape_runs

def test_upsert_market_snapshot_overwrites_same_day(conn):
    card = _card_raw()
    card.id = db.upsert_card(conn, card)
    db.upsert_market_snapshot(conn, card.id, "2026-08-01", 100.0, 5, 90.0, 120.0, fx_rate=150.0)
    # 同日再実行は行を増やさず上書き
    db.upsert_market_snapshot(conn, card.id, "2026-08-01", 105.0, 7, 92.0, 125.0, fx_rate=151.0)

    rows = db.market_history_for_card(conn, card.id)
    assert len(rows) == 1
    r = rows[0]
    assert r["date"] == "2026-08-01"
    assert r["median_usd"] == pytest.approx(105.0)
    assert r["count"] == 7
    assert r["min_usd"] == pytest.approx(92.0)
    assert r["max_usd"] == pytest.approx(125.0)
    assert r["fx_rate"] == pytest.approx(151.0)


def test_latest_scrape_runs_returns_latest_per_source(conn):
    r1 = db.start_scrape_run(conn, "ebay")
    db.finish_scrape_run(conn, r1, queries_total=10, queries_failed=1,
                         items_found=100, parse_failures=2, notes="old")
    r2 = db.start_scrape_run(conn, "ebay")
    db.finish_scrape_run(conn, r2, queries_total=20, queries_failed=0,
                         items_found=200, parse_failures=1, notes="new")
    r3 = db.start_scrape_run(conn, "mercari")
    db.finish_scrape_run(conn, r3, queries_total=5, queries_failed=0,
                         items_found=50, parse_failures=0)

    rows = db.latest_scrape_runs(conn)
    assert [r["source"] for r in rows] == ["ebay", "mercari"]  # source 昇順
    ebay = rows[0]
    assert ebay["id"] == r2  # ソースごとに最新の1件だけ
    assert ebay["queries_total"] == 20
    assert ebay["notes"] == "new"
    assert rows[1]["id"] == r3


def test_new_export_fields_first_seen_and_profit_model(conn):
    """サイト刷新で追加した first_seen_at / profit_model / site_url の出力確認。"""
    _, psa = _seed_cards_and_history(conn)
    deal = _make_mercari_deal(conn, psa, URL_A, buy_price_jpy=5000, profit_rate=0.4)
    db.rebuild_matches(conn, [deal])

    cfg = Config(
        {
            "threshold": {"min_profit_jpy": 5000, "min_profit_rate": 0.20, "min_sold_count_30d": 3},
            "export": {"site_url": "https://example.com/CardGap/"},
            "fx": {"conversion_margin": 0.02},
            "ebay_fees": {"final_value_fee": 0.1325},
            "buy_side": {"snkrdunk_buyer_fee_rate": 0.055, "snkrdunk_shipping_jpy": 1000},
        }
    )
    deals = export.build_deals_payload(cfg, conn)["deals"]
    # upsert_mercari 経由で入れた出品には first_seen_at が付く
    assert deals[0]["first_seen_at"] is not None

    summary = export.build_summary_payload(cfg, conn)
    assert summary["site_url"] == "https://example.com/CardGap/"
    pm = summary["profit_model"]
    assert pm["conversion_margin"] == 0.02
    assert pm["final_value_fee"] == 0.1325
    assert pm["buy"]["snkrdunk"]["fee_rate"] == 0.055
    assert pm["buy"]["mercari"]["fee_rate"] == 0.0  # 既定値で埋まる
