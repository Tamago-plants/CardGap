"""ナルト系シリーズ番号(DN/NM/NX/忍)とシリーズ監視機能のテスト。"""

from __future__ import annotations

import pytest

from cardgap import db
from cardgap.matching.engine import is_foreign_language, match_title
from cardgap.matching.extract import extract_series_number
from cardgap.matching.normalize import normalize_card_number, parse_series_number
from cardgap.models import CONF_HIGH, CONF_LOW, CONF_MEDIUM, CONF_NONE, Card
from cardgap.pipeline import _cards_for_source, _resolve_series_item
from cardgap.config import Config
from cardgap.scrape import ebay, mercari


@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


# ---------------------------------------------------------------- 抽出・正規化

def test_parse_series_number_variants():
    assert parse_series_number("DN-001") == ("dn", 1)
    assert parse_series_number("dn001") == ("dn", 1)
    assert parse_series_number("NM-123") == ("nm", 123)
    assert parse_series_number("NX-045") == ("nx", 45)
    assert parse_series_number("忍-001") == ("忍", 1)
    assert parse_series_number("201/190") is None


def test_normalize_card_number_series_and_legacy():
    assert normalize_card_number("DN-001") == "dn-1"
    assert normalize_card_number("忍-001") == "忍-1"
    assert normalize_card_number("087/100") == "87/100"
    assert normalize_card_number("No.25") == "25"
    assert normalize_card_number("no 25") == "25"  # noシリーズ扱いにしない


def test_extract_series_number_from_titles():
    assert extract_series_number("ナルティメットカードダス DN-001 うずまきナルト", "dn") == 1
    assert extract_series_number("NARUTO データカードダス DN001 美品", "DN") == 1
    assert extract_series_number("naruto data carddass DN 012 Sasuke", "dn") == 12
    assert extract_series_number("NARUTOカードゲーム 忍-001 うずまきナルト", "忍") == 1
    # 全角ハイフン・全角英数字は NFKC 正規化で拾える
    assert extract_series_number("カードダス ＤＮ−００３", "dn") == 3
    # 誤検知しないこと: PSA表記 / コンディションの NM(Near Mint)
    assert extract_series_number("PSA 10 データカードダス NX-021", "nx") == 21
    assert extract_series_number("Naruto card NM-MT 8 PSA", "nm") is None
    assert extract_series_number("Naruto carddass NM 7 rare", "nm") is None  # 1桁は番号扱いしない
    assert extract_series_number("該当なしのタイトル", "dn") is None


# ---------------------------------------------------------------- エンジン

def _dn001(psa=None):
    return Card(category="naruto", name_ja="ナルト カードダス", name_en="Naruto Data Carddass",
                set_code=None, card_number="DN-001", psa_grade=psa)


def test_match_title_series_number():
    assert match_title("ナルティメットカードダス DN-001 うずまきナルト 美品", _dn001()) == CONF_HIGH
    assert match_title("ナルティメットカードダス DN-002 うちはサスケ", _dn001()) == CONF_NONE
    assert match_title("Naruto Data Carddass DN001 Japanese", _dn001()) == CONF_HIGH
    # PSA ルールは従来どおり
    assert match_title("DN-001 うずまきナルト PSA10", _dn001()) == CONF_NONE
    assert match_title("DN-001 うずまきナルト PSA10", _dn001(psa=10)) == CONF_HIGH
    # 番号がタイトルに無ければ名前のみ → low
    assert match_title("ナルト カードダス キラ 美品", _dn001()) == CONF_LOW


def test_match_title_kanji_series():
    card = Card(category="naruto", name_ja="NARUTO カードゲーム", name_en="Naruto Card Game",
                set_code=None, card_number="忍-012", psa_grade=None)
    assert match_title("NARUTOカードゲーム 忍-012 はたけカカシ", card) == CONF_HIGH
    assert match_title("NARUTOカードゲーム 忍-013 うみのイルカ", card) == CONF_NONE


# ---------------------------------------------------------------- Card ヘルパ

def test_card_series_watch_helpers():
    watch = Card(category="naruto", name_ja="ナルト カードダス", name_en="Naruto Data Carddass",
                 set_code=None, card_number="DN-*", psa_grade=None)
    assert watch.is_series_watch()
    assert watch.series_prefix() == "DN"
    assert watch.query_number() == "DN"

    concrete = _dn001()
    assert not concrete.is_series_watch()
    assert concrete.query_number() == "DN-001"

    kanji = Card(category="naruto", name_ja="NARUTO カードゲーム", name_en="Naruto Card Game",
                 set_code=None, card_number="忍-*", psa_grade=None)
    assert kanji.series_prefix() == "忍"


def test_build_query_series():
    watch = Card(category="naruto", name_ja="ナルト カードダス", name_en="Naruto Data Carddass",
                 set_code=None, card_number="DN-*", psa_grade=None)
    assert ebay.build_query(watch) == "Naruto Data Carddass Japanese DN"
    assert mercari.build_query(watch) == "ナルト カードダス DN"

    kanji = Card(category="naruto", name_ja="NARUTO カードゲーム", name_en="Naruto Card Game",
                 set_code=None, card_number="忍-*", psa_grade=None)
    # 漢字プレフィックスは eBay クエリから外す(海外セラーのタイトルに含まれない)
    assert ebay.build_query(kanji) == "Naruto Card Game Japanese"
    assert mercari.build_query(kanji) == "NARUTO カードゲーム 忍"


# ---------------------------------------------------- シリーズ監視の解決

def _series_card(conn) -> Card:
    card = Card(category="naruto", name_ja="ナルト カードダス", name_en="Naruto Data Carddass",
                set_code=None, card_number="DN-*", psa_grade=None)
    card.id = db.upsert_card(conn, card)
    return card


def test_resolve_series_item_creates_and_reuses_card(conn):
    watch = _series_card(conn)
    cid = _resolve_series_item(conn, watch, "ナルティメットカードダス DN-001 うずまきナルト")
    assert cid is not None and cid != watch.id
    created = db.get_card(conn, cid)
    assert created.card_number == "DN-001"
    assert created.psa_grade is None
    assert created.auto_discovered
    assert created.display_name() == "ナルト カードダス DN-001"

    # 同じ番号は同じカードに解決される(再登録しない)
    again = _resolve_series_item(conn, watch, "DN-001 ナルト 美品 まとめ")
    assert again == cid

    # PSA10 は別カード
    graded = _resolve_series_item(conn, watch, "PSA10 ナルティメットカードダス DN-001")
    assert graded not in (None, cid)
    assert db.get_card(conn, graded).psa_grade == 10


def test_resolve_series_item_rejects(conn):
    watch = _series_card(conn)
    assert _resolve_series_item(conn, watch, "番号のないカードダス まとめ売り") is None
    assert _resolve_series_item(conn, watch, "Naruto Carddass DN-001 English version") is None
    assert _resolve_series_item(conn, watch, "PSA 8.5 DN-001 カードダス") is None  # 半グレードは対象外


def test_auto_discovered_cards_excluded_from_queries(conn):
    watch = _series_card(conn)
    _resolve_series_item(conn, watch, "ナルティメットカードダス DN-001 うずまきナルト")
    cfg = Config({"categories": {"naruto": {"enabled": True, "snkrdunk": False}}})
    cards = db.list_cards(conn)
    targets = _cards_for_source(cfg, cards, "ebay")
    # クエリ対象はシリーズ監視行のみ。自動登録された DN-001 は含まれない
    assert [c.card_number for c in targets] == ["DN-*"]
    # スニダン非対応カテゴリなので snkrdunk のクエリ対象は 0
    assert _cards_for_source(cfg, cards, "snkrdunk") == []


def test_manual_row_wins_over_auto(conn):
    watch = _series_card(conn)
    cid = _resolve_series_item(conn, watch, "DN-001 うずまきナルト カードダス")
    # 後から watchlist に手動行が入ったら auto フラグは 0 に戻り、以後クエリ対象になる
    manual = Card(category="naruto", name_ja="ナルト カードダス", name_en="Naruto Data Carddass",
                  set_code=None, card_number="DN-001", psa_grade=None, auto_discovered=False)
    assert db.upsert_card(conn, manual) == cid
    assert db.get_card(conn, cid).auto_discovered is False
