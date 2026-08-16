"""マッチングロジック(cardgap.matching)のテスト。

extract / normalize / names / engine をすべて純関数として検証する。
ネットワーク・Playwright・DB には依存しない。
"""

from __future__ import annotations

from cardgap.matching.engine import match_title
from cardgap.matching.extract import (
    extract_card_number,
    extract_carddass_number,
    extract_psa_grade,
    extract_set_code,
)
from cardgap.matching.names import NameDict, load_name_dict
from cardgap.matching.normalize import normalize, normalize_card_number
from cardgap.models import CONF_HIGH, CONF_LOW, CONF_MEDIUM, CONF_NONE, Card


def _card(**overrides) -> Card:
    """テスト用の基準カード(ポケモン / セット記号+番号+PSA10指定)。"""
    base = dict(
        category="pokemon",
        name_ja="リザードン",
        name_en="Charizard",
        set_code="s12a",
        card_number="201/190",
        psa_grade=10,
    )
    base.update(overrides)
    return Card(**base)


def _naruto_card(**overrides) -> Card:
    """カードダス系のカード(セット記号なし・番号のみ・raw)。"""
    base = dict(
        category="naruto",
        name_ja="うずまきナルト",
        name_en="Naruto Uzumaki",
        set_code=None,
        card_number="25",
        psa_grade=None,
    )
    base.update(overrides)
    return Card(**base)


# ------------------------------------------------------------------ match_title

def test_english_title_number_set_grade_all_match_is_high():
    title = "Pokemon Japanese s12a Charizard VSTAR 201/190 PSA 10"
    assert match_title(title, _card()) == CONF_HIGH


def test_number_and_grade_match_without_set_code_is_medium():
    # タイトルからセット記号が取れない → 番号一致のみで medium
    title = "Charizard VSTAR 201/190 PSA 10"
    assert match_title(title, _card()) == CONF_MEDIUM


def test_psa9_title_against_psa10_card_is_none():
    # グレード指定ありのカードはタイトルのグレード完全一致が必須
    title = "Pokemon Japanese s12a Charizard VSTAR 201/190 PSA 9"
    assert match_title(title, _card()) == CONF_NONE


def test_raw_card_against_psa10_title_is_none():
    # raw カードに PSA 品を混ぜない(相場が壊れるため)
    title = "Pokemon Japanese s12a Charizard VSTAR 201/190 PSA 10"
    assert match_title(title, _card(psa_grade=None)) == CONF_NONE


def test_raw_card_against_ungraded_title_with_number_and_set_is_high():
    title = "Pokemon Japanese s12a Charizard VSTAR 201/190"
    assert match_title(title, _card(psa_grade=None)) == CONF_HIGH


def test_same_number_but_different_set_code_is_none():
    # 番号が同じでもセット記号が明示的に食い違えば別カード
    title = "Pokemon Japanese sv2a Charizard VSTAR 201/190 PSA 10"
    assert match_title(title, _card()) == CONF_NONE


def test_different_card_number_is_none():
    title = "Pokemon Japanese s12a Charizard VSTAR 200/190 PSA 10"
    assert match_title(title, _card()) == CONF_NONE


def test_japanese_name_only_title_is_low():
    # 番号がタイトルに無く日本語名のみ → low(raw カード同士)
    title = "リザードンVSTAR SAR 美品"
    assert match_title(title, _card(psa_grade=None)) == CONF_LOW


def test_fullwidth_digits_and_slash_are_normalized():
    # 全角数字・全角スラッシュ・全角PSA表記が NFKC 正規化されて一致する
    title = "リザードン ２０１／１９０ PSA１０"
    # セット記号はタイトルに無いので medium(none にならないことが重要)
    assert match_title(title, _card()) == CONF_MEDIUM


def test_carddass_no_style_number_is_high():
    # スラッシュ無し番号のカードダスは "No.25" 形式で拾い、セット指定なし同士は high
    title = "ナルティメットカードダス No.25 うずまきナルト"
    assert match_title(title, _naruto_card()) == CONF_HIGH


def test_carddass_different_number_is_none():
    title = "ナルティメットカードダス No.26 うずまきナルト"
    assert match_title(title, _naruto_card()) == CONF_NONE


# --------------------------------------------------------------------- extract

def test_extract_card_number_strips_leading_zeros():
    assert extract_card_number("087/100") == "87/100"


def test_extract_card_number_missing_is_none():
    assert extract_card_number("リザードンVSTAR SAR 美品") is None


def test_extract_set_code_does_not_misfire_on_psa():
    # "psa 10" の "sa"/"a 10" 等からセット記号を誤検出しない
    assert extract_set_code("psa 10") is None


def test_extract_set_code_detects_sv4a():
    assert extract_set_code("PSA 10 Charizard sv4a") == "sv4a"


def test_extract_psa_grade_half_grade():
    assert extract_psa_grade("PSA 8.5") == 8.5


def test_extract_psa_grade_absent_is_none():
    assert extract_psa_grade("Charizard VSTAR 201/190") is None


def test_extract_carddass_number():
    assert extract_carddass_number("ナルティメットカードダス No.025") == "25"


# ------------------------------------------------------------------- normalize

def test_normalize_card_number_variants():
    assert normalize_card_number("087/100") == "87/100"
    assert normalize_card_number("No.25") == "25"
    assert normalize_card_number("abc") is None


# ----------------------------------------------------------------------- names

def test_name_dict_translation_match():
    # 辞書に登録した対訳(英名)がタイトルに含まれれば True
    nd = NameDict()
    nd.ja_to_en[normalize("リザードン")] = "Charizard"
    nd.en_to_ja[normalize("Charizard")] = "リザードン"
    assert nd.title_contains_name(
        "Pokemon Charizard VSTAR PSA 10", "リザードン", "リザードンVSTAR"
    )
    # 辞書が空だと日英表記が食い違うタイトルは拾えない
    assert not NameDict().title_contains_name(
        "Pokemon Charizard VSTAR PSA 10", "リザードン", "リザードンVSTAR"
    )


def test_match_title_low_via_name_dict():
    # タイトルに番号が無くても辞書経由の対訳名一致で low になる
    nd = NameDict()
    nd.ja_to_en[normalize("リザードン")] = "Charizard"
    card = _card(psa_grade=None, name_en="Lizardon")  # 英名の表記ゆれを辞書で吸収
    assert match_title("Charizard VSTAR SAR", card, name_dict=nd) == CONF_LOW


def test_load_name_dict(tmp_path):
    p = tmp_path / "names.csv"
    p.write_text("name_ja,name_en\nリザードン,Charizard\n,\n", encoding="utf-8")
    nd = load_name_dict(p)
    assert nd.ja_to_en[normalize("リザードン")] == "Charizard"
    assert nd.en_to_ja[normalize("Charizard")] == "リザードン"
    # 存在しないパスは空辞書(例外にしない)
    assert load_name_dict(tmp_path / "missing.csv").ja_to_en == {}


# ------------------------------------------------ レビューで発見したバグの回帰テスト

def test_cjk_adjacent_extraction():
    """\\b は CJK 文字に隣接すると境界にならない(Python の \\w は漢字かなを含む)。

    ASCII lookaround 境界に変えた回帰テスト。メルカリの典型タイトルは
    「PSA10鑑定済」のように空白なしの日本語連結。
    """
    from cardgap.matching.extract import (
        extract_card_number,
        extract_carddass_number,
        extract_psa_grade,
        extract_set_code,
    )

    assert extract_psa_grade("PSA10鑑定済 リザードンVSTAR") == 10.0
    assert extract_psa_grade("美品psa10横線なし") == 10.0
    assert extract_psa_grade("psa100枚セット") is None  # 誤検知しない
    assert extract_card_number("リザードンex201/165美品") == "201/165"
    assert extract_card_number("2023/12/01発売") is None  # 日付は拾わない
    assert extract_carddass_number("No.25うずまきナルト") == "25"
    assert extract_set_code("s12aスペシャルアートセット") == "s12a"


def test_cjk_adjacent_grade_affects_matching():
    """「PSA10鑑定済」タイトルが raw 相場に high 混入しないこと(逆に PSA10 指定には high)。"""
    title = "PSA10鑑定済 リザードンVSTAR 201/190 s12a"
    raw = _card(psa_grade=None)
    psa10 = _card(psa_grade=10)
    assert match_title(title, raw) == CONF_NONE
    assert match_title(title, psa10) == CONF_HIGH


def test_foreign_language_titles_rejected():
    """日本語版のみ対象: 英語版等が明示されたタイトルは番号が一致しても none。

    英語版「Pokemon 151」は sv2a と同じコレクター番号(201/165 等)を持つため、
    言語マーカーで弾かないと相場に混入する。
    """
    card = Card(
        category="pokemon",
        name_ja="リザードンex",
        name_en="Charizard ex",
        set_code="sv2a",
        card_number="201/165",
        psa_grade=None,
    )
    assert match_title("Pokemon 151 Charizard ex 201/165 ENGLISH NM", card) == CONF_NONE
    assert match_title("ポケモンカード 英語版 リザードンex sv2a 201/165", card) == CONF_NONE
    assert match_title("Pokemon Charizard ex 201/165 Korean", card) == CONF_NONE
    # 日本語版(Japanese 表記や無表記)は通常どおり判定される
    assert match_title("Pokemon Japanese sv2a Charizard ex 201/165", card) == CONF_HIGH
