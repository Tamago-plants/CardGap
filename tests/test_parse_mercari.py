"""メルカリ スクレイパーのテスト(ネットワーク・Playwright 不要。パーサは純関数)。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus

from cardgap.models import Card
from cardgap.scrape import mercari

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mercari_search_sample.html"


def _load_fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _card(psa_grade: int | None) -> Card:
    return Card(
        category="pokemon",
        name_ja="リザードンVSTAR",
        name_en="Charizard VSTAR",
        set_code="s12a",
        card_number="201/190",
        psa_grade=psa_grade,
    )


def test_parse_counts_and_failures():
    """正常セル(実DOM準拠の海外IP表示セル含む7件)を返し、価格の無い壊れた1件は parse_failures に積む。"""
    parsed = mercari.parse_search_html(_load_fixture(), raw_query="リザードン")
    assert len(parsed.items) == 7
    assert parsed.parse_failures == 1
    assert parsed.errors  # 失敗の内訳が errors に残っている


def test_price_not_taken_from_title():
    """タイトル内の金額(定価¥3,000)ではなく価格要素の ¥12,500 を採用する。"""
    parsed = mercari.parse_search_html(_load_fixture())
    item = parsed.items[5]
    assert "定価" in item.title
    assert item.price_jpy == 12500


def test_parse_first_item_fields():
    """1件目: タイトル(alt接尾辞除去)・価格int・絶対URL(クエリ無し)・画像URL。"""
    parsed = mercari.parse_search_html(_load_fixture(), raw_query="リザードン")
    item = parsed.items[0]
    assert item.title == "【PSA10】リザードンVSTAR 201/190 s12a"
    assert isinstance(item.price_jpy, int)
    assert item.price_jpy == 39800  # カンマ除去済み
    assert item.listing_url == "https://jp.mercari.com/item/m12345678901"
    assert "?" not in item.listing_url
    assert item.image_url == (
        "https://static.mercdn.net/c!/w=240/thumb/photos/m12345678901_1.jpg"
    )
    # 検索一覧からは取れない項目
    assert item.condition is None
    assert item.listed_at is None
    assert item.raw_query == "リザードン"


def test_parse_title_fallback_when_alt_empty():
    """img alt が空のセルは thumbnail-item-name のテキストにフォールバックする。"""
    parsed = mercari.parse_search_html(_load_fixture())
    assert parsed.items[2].title == "ピカチュウ AR 美品"


def test_parse_empty_page_warns():
    """商品セル0件でも例外にせず、警告を errors に残す。"""
    parsed = mercari.parse_search_html("<html><body></body></html>", raw_query="リザードン")
    assert parsed.items == []
    assert parsed.parse_failures == 0
    assert parsed.errors


def test_build_query_with_psa_grade():
    """psa_grade=10 なら空白なしの 'PSA10' 表記がクエリに入る。"""
    q = mercari.build_query(_card(psa_grade=10))
    assert "リザードンVSTAR" in q
    assert "201/190" in q
    assert "PSA10" in q
    assert "PSA 10" not in q


def test_build_query_raw_card_has_no_psa():
    """rawカード(psa_grade=None)には PSA を付けない。"""
    q = mercari.build_query(_card(psa_grade=None))
    assert "PSA" not in q


def test_build_search_url():
    """keyword がエンコードされ、販売中のみ・価格昇順のパラメータを含む。"""
    query = "リザードンVSTAR 201/190 PSA10"
    url = mercari.build_search_url(query)
    assert url.startswith("https://jp.mercari.com/search?keyword=")
    assert quote_plus(query) in url
    assert "status=on_sale" in url
    assert "sort=price" in url
    assert "order=asc" in url


def test_parse_overseas_display_and_skeleton():
    """実DOM準拠: 海外IP表示(US$)のセルは aria-label の円価格で取れ、
    merSkeleton(未描画プレースホルダ)は失敗にカウントされない。"""
    page = mercari.parse_search_html(_load_fixture(), raw_query="test")
    shino = [i for i in page.items if "油女シノ" in i.title]
    assert len(shino) == 1
    assert shino[0].price_jpy == 300  # US$1.98 ではなく aria-label の 300円
    assert shino[0].listing_url == "https://jp.mercari.com/item/m99900000001"
    # スケルトンは items にも parse_failures にも入らない(元の失敗1件のみ)
    assert page.parse_failures == 1
