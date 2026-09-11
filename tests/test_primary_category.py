"""優先カテゴリ(export.primary_category)機能のテスト。

対象:
  - export.build_summary_payload の新キー
      primary_category / categories / *_by_category ボード
    (カテゴリ別ボードはグローバル top_n カット前の全行から作られること)
  - notify のダイジェストが優先カテゴリを先頭に出すこと
  - 旧 summary.json(新キーなし)では従来どおりの出力になること(後方互換)

DB は :memory:、ネットワークには一切出ない。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from cardgap import db, export, notify, pipeline
from cardgap.config import Config
from cardgap.models import CONF_HIGH, Card, MercariListing


# -------------------------------------------------------------------- fixtures

@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


def _cfg(primary: str | None = "naruto", top_n: int = 3, movers_n: int = 2) -> Config:
    """export / recompute_matches が参照するキー一式(ファイル非依存)。

    top_n=3 / movers_n=2 と小さくして「グローバルカットで落ちる行」を
    少ないシードで作れるようにする。閾値も低めにして少額の案件が above に入る。
    """
    export_cfg: dict = {"history_days": 90, "top_n": top_n, "movers_n": movers_n}
    if primary is not None:
        export_cfg["primary_category"] = primary
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
                "min_profit_jpy": 500,
                "min_profit_rate": 0.20,
                "min_sold_count_30d": 3,
            },
            "scrape": {"ebay_lookback_days": 30},
            "market": {"source": "auto"},
            "mercari_sell": {"fee_rate": 0.10, "shipping_jpy": 210},
            "export": export_cfg,
        }
    )


def _day(offset: int) -> str:
    return (date.today() - timedelta(days=offset)).isoformat()


def _card(category: str, name_ja: str, number: str) -> Card:
    return Card(
        category=category,
        name_ja=name_ja,
        name_en=f"card {number}",
        set_code=None,
        card_number=number,
        psa_grade=None,
    )


def _add_card(conn, category: str, name_ja: str, number: str) -> Card:
    card = _card(category, name_ja, number)
    card.id = db.upsert_card(conn, card)
    return card


def _snap(conn, card: Card, day_offset: int, median: float, count: int) -> None:
    db.upsert_mercari_market_snapshot(
        conn, card.id, _day(day_offset), median, count, median * 0.9, median * 1.1
    )


def _seed_deal(
    conn, category: str, name_ja: str, number: str, sold_median: int, buy_price: int
) -> Card:
    """SOLD 3件(中央値 sold_median)+ 販売中1件(buy_price)で案件1件分を作る。"""
    card = _add_card(conn, category, name_ja, number)
    db.upsert_mercari_sold(
        conn,
        [
            MercariListing(
                title=f"{name_ja} SOLD",
                price_jpy=p,
                condition=None,
                image_url=None,
                listing_url=f"https://jp.mercari.com/item/sold-{number}-{i}",
                card_id=card.id,
                match_confidence=CONF_HIGH,
            )
            for i, p in enumerate((sold_median - 200, sold_median, sold_median + 200))
        ],
    )
    db.upsert_mercari(
        conn,
        [
            MercariListing(
                title=f"{name_ja} 出品中",
                price_jpy=buy_price,
                condition=None,
                image_url=None,
                listing_url=f"https://jp.mercari.com/item/active-{number}",
                card_id=card.id,
                match_confidence=CONF_HIGH,
            )
        ],
    )
    return card


# ------------------------------------------------------------ summary payload

def test_summary_primary_category_and_categories(conn):
    naruto = _add_card(conn, "naruto", "うずまきナルト", "忍-001")
    pokemon = _add_card(conn, "pokemon", "ピカチュウ", "001/100")
    _snap(conn, naruto, 0, 3000.0, 1)
    _snap(conn, pokemon, 0, 5000.0, 10)
    summary = export.build_summary_payload(_cfg("naruto"), conn)
    assert summary["primary_category"] == "naruto"
    # データに実際に現れるカテゴリだけがソート済みで載る
    assert summary["categories"] == ["naruto", "pokemon"]


def test_summary_primary_category_null_when_unset(conn):
    # キー未設定でも空文字でも None(= JSON では null)になる
    assert export.build_summary_payload(_cfg(primary=None), conn)["primary_category"] is None
    assert export.build_summary_payload(_cfg(primary=""), conn)["primary_category"] is None


def test_top_selling_by_category_keeps_naruto_dropped_from_global(conn):
    """グローバル top_n がポケモン一色でも、カテゴリ別ボードにはナルトが残る。"""
    pokemons = [
        _add_card(conn, "pokemon", f"ポケモン{i}", f"{i:03d}/100") for i in range(4)
    ]
    naruto = _add_card(conn, "naruto", "うずまきナルト", "忍-001")
    for i, p in enumerate(pokemons):
        _snap(conn, p, 0, 1000.0, 10 - i)  # 件数 10, 9, 8, 7
    _snap(conn, naruto, 0, 3000.0, 1)      # 件数 1(グローバル top3 に入らない)
    summary = export.build_summary_payload(_cfg("naruto", top_n=3), conn)

    top = summary["mercari_top_selling"]
    assert [t["card_id"] for t in top] == [p.id for p in pokemons[:3]]  # 全部ポケモン
    by_cat = summary["mercari_top_selling_by_category"]
    # カット後のグローバルリストからではなく、カット前の全行から作られている
    assert [t["card_id"] for t in by_cat["naruto"]] == [naruto.id]
    # カテゴリ内でも top_n でカットされる(ポケモン4枚 → 3件)
    assert [t["card_id"] for t in by_cat["pokemon"]] == [p.id for p in pokemons[:3]]


def test_mercari_movers_by_category_cut_and_order(conn):
    """騰落のカテゴリ別ボード: グローバルと同じソート順・movers_n カット。"""
    ups = []
    for i, rate_pct in enumerate((30, 20, 10)):
        c = _add_card(conn, "pokemon", f"上昇{i}", f"U{i:03d}/100")
        _snap(conn, c, 1, 1000.0, 5)
        _snap(conn, c, 0, 1000.0 + rate_pct * 10, 5)
        ups.append(c)
    n_up = _add_card(conn, "naruto", "上昇ナルト", "忍-101")
    _snap(conn, n_up, 1, 1000.0, 5)
    _snap(conn, n_up, 0, 1050.0, 5)  # +5%(グローバル top2 に入らない)

    downs = []
    for i, rate_pct in enumerate((30, 20, 10)):
        c = _add_card(conn, "pokemon", f"下落{i}", f"D{i:03d}/100")
        _snap(conn, c, 1, 1000.0, 5)
        _snap(conn, c, 0, 1000.0 - rate_pct * 10, 5)
        downs.append(c)
    n_down = _add_card(conn, "naruto", "下落ナルト", "忍-102")
    _snap(conn, n_down, 1, 1000.0, 5)
    _snap(conn, n_down, 0, 950.0, 5)  # -5%

    summary = export.build_summary_payload(_cfg("naruto", movers_n=2), conn)
    # グローバルは movers_n=2 カットでポケモンのみ
    assert [m["card_id"] for m in summary["mercari_movers_up"]] == [ups[0].id, ups[1].id]
    assert [m["card_id"] for m in summary["mercari_movers_down"]] == [downs[0].id, downs[1].id]
    up_cat = summary["mercari_movers_up_by_category"]
    down_cat = summary["mercari_movers_down_by_category"]
    # カテゴリ内も同じソート順(上昇率降順 / 下落率昇順)+ movers_n カット
    assert [m["card_id"] for m in up_cat["pokemon"]] == [ups[0].id, ups[1].id]
    assert [m["card_id"] for m in up_cat["naruto"]] == [n_up.id]
    assert [m["card_id"] for m in down_cat["pokemon"]] == [downs[0].id, downs[1].id]
    assert [m["card_id"] for m in down_cat["naruto"]] == [n_down.id]


def test_top_by_rate_by_category_shapes_and_order(conn):
    """案件ランキングのカテゴリ別ボード: 行形状はグローバルと同一・利益率降順。"""
    cfg = _cfg("naruto", top_n=3)
    a = _seed_deal(conn, "naruto", "うずまきナルト", "忍-001", 3000, 1500)   # 率0.66
    b = _seed_deal(conn, "naruto", "うちはサスケ", "忍-002", 2000, 1000)    # 率0.59
    c = _seed_deal(conn, "pokemon", "ピカチュウ", "001/100", 5000, 2000)   # 率1.145
    pipeline.recompute_matches(cfg, conn, fx_rate=150.0)
    summary = export.build_summary_payload(cfg, conn)

    # グローバルは3件とも above(閾値 500円 / 20%)
    assert [r["card_id"] for r in summary["top_by_rate"]] == [c.id, a.id, b.id]
    by_rate = summary["top_by_rate_by_category"]
    assert [r["card_id"] for r in by_rate["naruto"]] == [a.id, b.id]  # 率降順
    assert [r["card_id"] for r in by_rate["pokemon"]] == [c.id]
    by_profit = summary["top_by_profit_by_category"]
    assert [r["card_id"] for r in by_profit["naruto"]] == [a.id, b.id]  # 990 > 590
    # 行形状はグローバル版と同一(サイト側が同じレンダラを使える)
    assert by_rate["naruto"][0] == summary["top_by_rate"][1]


# ------------------------------------------------------------ digest: ranking

def _rank_entry(display_name: str, profit_rate: float = 0.42) -> dict:
    return {
        "display_name": display_name,
        "source": "mercari",
        "buy_price_jpy": 5000,
        "profit_jpy": 10000.0,
        "profit_rate": profit_rate,
        "listing_url": "https://jp.mercari.com/item/m1",
    }


def test_digest_ranking_uses_primary_list_and_label():
    summary = {
        "primary_category": "naruto",
        "top_by_rate": [_rank_entry("ピカチュウ 001/100")],
        "top_by_rate_by_category": {
            "naruto": [_rank_entry("うずまきナルト 忍-001")],
            "pokemon": [_rank_entry("ピカチュウ 001/100")],
        },
    }
    embed = notify._digest_ranking_embed(summary)
    assert embed["title"] == "利益率ランキング TOP5(ナルト)"
    assert "うずまきナルト 忍-001" in embed["description"]
    assert "ピカチュウ" not in embed["description"]


def test_digest_ranking_falls_back_to_global_when_primary_list_empty():
    summary = {
        "primary_category": "naruto",
        "top_by_rate": [_rank_entry("ピカチュウ 001/100")],
        "top_by_rate_by_category": {"pokemon": [_rank_entry("ピカチュウ 001/100")]},
    }
    embed = notify._digest_ranking_embed(summary)
    assert embed["title"] == "利益率ランキング TOP5"  # ラベルなし
    assert "ピカチュウ 001/100" in embed["description"]


def test_digest_ranking_unchanged_without_new_keys():
    """旧 summary.json(primary_category キーなし)では従来どおり。"""
    summary = {"top_by_rate": [_rank_entry("ピカチュウ 001/100")]}
    embed = notify._digest_ranking_embed(summary)
    assert embed["title"] == "利益率ランキング TOP5"
    assert "ピカチュウ 001/100" in embed["description"]


# ------------------------------------------------------------ digest: mercari

def _mover(display_name: str, prev: float, cur: float, rate: float) -> dict:
    return {
        "display_name": display_name,
        "prev_median_jpy": prev,
        "median_jpy": cur,
        "change_rate": rate,
    }


def _seller(display_name: str, count: int, median: float, category: str) -> dict:
    return {
        "display_name": display_name,
        "count": count,
        "median_jpy": median,
        "category": category,
    }


def test_digest_mercari_primary_first_with_other_categories_tail():
    summary = {
        "primary_category": "naruto",
        "mercari_movers_up_by_category": {
            "naruto": [_mover("忍-001", 3000.0, 3300.0, 0.1)],
            "pokemon": [_mover("001/100", 500.0, 900.0, 0.8)],
        },
        "mercari_movers_down_by_category": {
            "naruto": [_mover("忍-002", 1000.0, 800.0, -0.2)],
        },
        "mercari_top_selling_by_category": {
            "naruto": [_seller("忍-002", 8, 800.0, "naruto")],
            # 4件入れて「3件で打ち切り」を検証。並びは件数降順に整列される
            "pokemon": [
                _seller("001/100", 20, 500.0, "pokemon"),
                _seller("002/100", 15, 400.0, "pokemon"),
                _seller("003/100", 7, 300.0, "pokemon"),
                _seller("004/100", 6, 200.0, "pokemon"),
            ],
        },
        # グローバル top_n が優先カテゴリで埋まっていても(=他カテゴリ行なし)、
        # 他カテゴリの売れ筋はカテゴリ別ボードから拾えることを検証する
        "mercari_top_selling": [
            _seller("忍-002", 8, 800.0, "naruto"),
        ],
    }
    embed = notify._digest_mercari_embed(summary)
    assert embed is not None and embed["title"] == "メルカリ相場"
    lines = embed["description"].split("\n")
    assert lines == [
        "📈 忍-001 ¥3,000 → ¥3,300 (+10.0%)",
        "📉 忍-002 ¥1,000 → ¥800 (-20.0%)",
        "— 売れ筋(直近30日の売れた数)—",
        "1. 忍-002 8件 / 中央値¥800",
        "— 他カテゴリの売れ筋 —",
        # primary 以外の行だけ・最大3件(4件目の 004/100 は落ちる)
        "1. 001/100 20件 / 中央値¥500",
        "2. 002/100 15件 / 中央値¥400",
        "3. 003/100 7件 / 中央値¥300",
    ]


def test_digest_mercari_no_other_section_when_only_primary():
    summary = {
        "primary_category": "naruto",
        "mercari_top_selling_by_category": {
            "naruto": [_seller("忍-002", 8, 800.0, "naruto")],
        },
        "mercari_top_selling": [_seller("忍-002", 8, 800.0, "naruto")],
    }
    embed = notify._digest_mercari_embed(summary)
    assert "他カテゴリ" not in embed["description"]


def test_digest_mercari_falls_back_to_global_when_primary_lists_empty():
    """primary が設定されていてもそのカテゴリのデータが空ならグローバル表示。"""
    summary = {
        "primary_category": "naruto",
        "mercari_movers_up_by_category": {"pokemon": [_mover("001/100", 500.0, 900.0, 0.8)]},
        "mercari_top_selling_by_category": {},
        "mercari_movers_up": [_mover("001/100", 500.0, 900.0, 0.8)],
        "mercari_top_selling": [_seller("001/100", 20, 500.0, "pokemon")],
    }
    embed = notify._digest_mercari_embed(summary)
    lines = embed["description"].split("\n")
    assert lines == [
        "📈 001/100 ¥500 → ¥900 (+80.0%)",
        "— 売れ筋(直近30日の売れた数)—",
        "1. 001/100 20件 / 中央値¥500",
    ]


def test_digest_mercari_unchanged_without_new_keys():
    """旧 summary.json(新キーなし)では従来どおりの行構成・None 判定。"""
    summary = {
        "mercari_movers_up": [_mover("忍-001", 3000.0, 3300.0, 0.1)],
        "mercari_movers_down": [],
        "mercari_top_selling": [{"display_name": "忍-002", "count": 8, "median_jpy": 800.0}],
    }
    embed = notify._digest_mercari_embed(summary)
    assert embed["description"].split("\n") == [
        "📈 忍-001 ¥3,000 → ¥3,300 (+10.0%)",
        "— 売れ筋(直近30日の売れた数)—",
        "1. 忍-002 8件 / 中央値¥800",
    ]
    assert notify._digest_mercari_embed({}) is None


def test_digest_mercari_none_when_primary_set_but_no_data():
    summary = {
        "primary_category": "naruto",
        "mercari_movers_up_by_category": {},
        "mercari_movers_down_by_category": {},
        "mercari_top_selling_by_category": {},
        "mercari_movers_up": [],
        "mercari_movers_down": [],
        "mercari_top_selling": [],
    }
    assert notify._digest_mercari_embed(summary) is None
