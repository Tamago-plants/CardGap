"""eBay Sold パーサ(cardgap.scrape.ebay)のテスト。

ネットワーク・Playwright には依存しない。フィクスチャHTMLに対する
純関数 parse_search_html / build_query / build_search_url を検証する。
"""

from __future__ import annotations

from pathlib import Path

from cardgap.models import Card
from cardgap.scrape import ebay

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture() -> str:
    return (FIXTURES / "ebay_sold_sample.html").read_text(encoding="utf-8")


def _card(**overrides) -> Card:
    base = dict(
        category="pokemon",
        name_ja="リザードンVSTAR",
        name_en="Charizard VSTAR",
        set_code="s12a",
        card_number="201/190",
        psa_grade=10,
    )
    base.update(overrides)
    return Card(**base)


# ---------------------------------------------------------- parse_search_html

def test_parse_counts_and_failures():
    page = ebay.parse_search_html(_load_fixture(), raw_query="charizard vstar s12a")
    # プレースホルダは黙ってスキップ、正常5件、壊れた1件は failures に積む
    assert len(page.items) == 5
    assert page.parse_failures == 1
    assert any("ebay item parse failed" in e for e in page.errors)


def test_item_a_psa10():
    page = ebay.parse_search_html(_load_fixture(), raw_query="q")
    a = page.items[0]
    assert a.title == "Pokemon Japanese s12a Charizard VSTAR 201/190 PSA 10"
    assert a.price_usd == 450.0
    assert a.shipping_usd == 0.0  # Free shipping
    assert a.sold_at == "2026-07-20"
    assert a.psa_grade == 10
    # トラッキング用のクエリ文字列は削られている
    assert "?" not in a.listing_url
    assert a.listing_url == "https://www.ebay.com/itm/256011111111"
    assert a.image_url == "https://i.ebayimg.com/images/g/aaaAAOSw/s-l500.jpg"
    assert a.raw_query == "q"


def test_range_price_uses_lower_bound():
    page = ebay.parse_search_html(_load_fixture())
    b = page.items[1]
    assert b.price_usd == 300.0  # "$300.00 to $350.00" は下限を採用
    assert b.shipping_usd == 10.0  # "+$10.00 shipping"


def test_raw_item_has_no_psa_grade():
    page = ebay.parse_search_html(_load_fixture())
    c = page.items[2]
    assert c.psa_grade is None
    # lazy-load 画像(data-src のみ)も拾える
    assert c.image_url == "https://i.ebayimg.com/images/g/cccAAOSw/s-l500.jpg"


def test_psa9_item():
    page = ebay.parse_search_html(_load_fixture())
    d = page.items[3]
    assert d.psa_grade == 9


def test_plain_item_shipping():
    page = ebay.parse_search_html(_load_fixture())
    e = page.items[4]
    assert e.shipping_usd == 5.25
    assert e.sold_at == "2026-08-01"  # span.POSITIVE のみのキャプションからも取れる


def test_no_items_adds_error():
    page = ebay.parse_search_html("<html><body><p>captcha</p></body></html>")
    assert page.items == []
    assert any("no items parsed" in e for e in page.errors)


# --------------------------------------------- build_query / build_search_url

def test_build_query_with_psa():
    card = _card()
    # 日本語版限定のため 'Japanese' が必ず入る
    assert ebay.build_query(card) == "Charizard VSTAR Japanese s12a 201/190 PSA 10"


def test_build_query_without_psa_and_missing_fields():
    card = _card(
        category="naruto",
        name_ja="うずまきナルト",
        name_en="Naruto Uzumaki",
        set_code=None,
        card_number="25",
        psa_grade=None,
    )
    # None のフィールドは飛ばし、raw カードには PSA を付けない
    assert ebay.build_query(card) == "Naruto Uzumaki Japanese 25"


def test_build_search_url():
    url = ebay.build_search_url("Charizard VSTAR s12a 201/190 PSA 10")
    assert url == (
        "https://www.ebay.com/sch/i.html"
        "?_nkw=Charizard+VSTAR+s12a+201%2F190+PSA+10"
        "&LH_Sold=1&LH_Complete=1&_ipg=120"
    )


def test_module_contract():
    assert ebay.SOURCE == "ebay"
    assert ebay.WAIT_SELECTOR == "li.s-item"
