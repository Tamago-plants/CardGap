"""スニダン スクレイパーのテスト(ネットワーク・Playwright 不要。パーサは純関数)。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus

from cardgap.models import Card
from cardgap.scrape import snkrdunk

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "snkrdunk_search_sample.html"


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
    """正常4件を返す。スニーカーと価格 "--" は含まれず、名前の無い壊れた1件だけ失敗に積む。"""
    parsed = snkrdunk.parse_search_html(_load_fixture(), raw_query="リザードン")
    assert len(parsed.items) == 4
    assert parsed.parse_failures == 1
    # 出品なし("--")のスキップは errors に積まれない → 内訳は壊れた1件分だけ
    assert len(parsed.errors) == 1


def test_parse_excludes_non_trading_cards():
    """href が /trading-cards/ 以外(スニーカー等)は商品として列挙されない。"""
    parsed = snkrdunk.parse_search_html(_load_fixture())
    assert all("/trading-cards/" in it.product_url for it in parsed.items)
    assert not any("/sneakers/" in it.product_url for it in parsed.items)


def test_parse_first_item_fields():
    """1件目: 商品名・最安価格int(カンマ除去)・絶対URL(クエリ無し)・画像URL。"""
    parsed = snkrdunk.parse_search_html(_load_fixture(), raw_query="リザードン")
    item = parsed.items[0]
    assert item.product_name == "リザードンVSTAR SAR s12a 201/190"
    assert isinstance(item.min_price_jpy, int)
    assert item.min_price_jpy == 55000  # カンマ除去済み
    assert item.product_url == "https://snkrdunk.com/trading-cards/12345"
    assert "?" not in item.product_url
    assert item.image_url == "https://images.snkrdunk.com/trading-cards/12345_1.jpg"
    assert item.raw_query == "リザードン"


def test_parse_fullwidth_yen_price():
    """全角円記号・空白入りの価格('￥ 128,000')もパースできる。"""
    parsed = snkrdunk.parse_search_html(_load_fixture())
    assert parsed.items[1].min_price_jpy == 128000


def test_parse_name_fallback_to_img_alt():
    """商品名要素が無いカードは img alt にフォールバックする。"""
    parsed = snkrdunk.parse_search_html(_load_fixture())
    assert parsed.items[3].product_name == "ピカチュウ AR s12a 205/190"


def test_parse_empty_page_warns():
    """商品カード0件でも例外にせず、警告を errors に残す。"""
    parsed = snkrdunk.parse_search_html("<html><body></body></html>", raw_query="リザードン")
    assert parsed.items == []
    assert parsed.parse_failures == 0
    assert parsed.errors


def test_build_query_has_no_psa_grade():
    """psa_grade 指定があってもクエリに PSA を付けない(スニダンはPSA品が別商品マスタ)。"""
    q = snkrdunk.build_query(_card(psa_grade=10))
    assert "リザードンVSTAR" in q
    assert "201/190" in q
    assert "PSA" not in q


def test_build_query_without_card_number():
    """card_number が無いカードは日本語名のみのクエリになる。"""
    card = _card(psa_grade=None)
    card.card_number = None
    assert snkrdunk.build_query(card) == "リザードンVSTAR"


def test_build_search_url():
    """keyword がエンコードされて snkrdunk.com の検索URLになる。"""
    query = "リザードンVSTAR 201/190"
    url = snkrdunk.build_search_url(query)
    assert url.startswith("https://snkrdunk.com/search?keyword=")
    assert quote_plus(query) in url
