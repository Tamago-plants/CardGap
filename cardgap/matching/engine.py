"""同一カード判定。

confidence の意味:
  high   : カード番号一致 + セット記号一致(watchlist にセット指定がある場合)
           + PSAグレード条件一致
  medium : カード番号一致 + PSAグレード条件一致(セット記号がタイトルから取れない)
  low    : カード名のみ一致 + PSAグレード条件一致(番号がタイトルから取れない)
  none   : 不一致。番号・セット・グレードのどれかが「明示的に食い違う」場合も none
           (例: 同じ 201/190 でもセットが違う、PSA9 出品を PSA10 カードに当てる等)

PSAグレード条件:
  watchlist でグレード指定あり → タイトルのグレードが完全一致すること
  watchlist が raw(グレード None)→ タイトルに PSA表記が無いこと
  (PSA品を raw 相場に混ぜると価格が壊れるため厳格にしている)
"""

from __future__ import annotations

from ..models import CONF_HIGH, CONF_LOW, CONF_MEDIUM, CONF_NONE, Card
from .extract import (
    extract_card_number,
    extract_carddass_number,
    extract_psa_grade,
    extract_series_number,
    extract_set_code,
)
from .names import NameDict
from .normalize import normalize, normalize_card_number, parse_series_number

# 対象は日本語版のみ。英語版などはコレクター番号が同一でも別相場のため、
# 他言語であることが明示されたタイトルは問答無用で除外する
# (例: 英語版「Pokemon 151」は sv2a と同じ 201/165 等の番号を持つ)。
_FOREIGN_LANGUAGE_MARKERS = (
    "english", "英語", "korean", "韓国語", "韓国版", "chinese", "中国語", "中文",
    "german", "french", "italian", "spanish", "portuguese",
)


def _is_foreign_language(title_norm: str) -> bool:
    return any(marker in title_norm for marker in _FOREIGN_LANGUAGE_MARKERS)


def is_foreign_language(title: str) -> bool:
    """日本語版以外(英語版等)が明示されたタイトルか。pipeline のシリーズ監視でも使う。"""
    return _is_foreign_language(normalize(title))


def _grade_ok(card: Card, title: str) -> bool:
    title_grade = extract_psa_grade(title)
    if card.psa_grade is None:
        return title_grade is None
    return title_grade is not None and float(card.psa_grade) == title_grade


def match_title(title: str, card: Card, name_dict: NameDict | None = None) -> str:
    """タイトルが watchlist カードと同一かを判定して confidence を返す。"""
    if _is_foreign_language(normalize(title)):
        return CONF_NONE  # 日本語版のみ対象(英語版等は同番号でも別相場)
    if not _grade_ok(card, title):
        return CONF_NONE

    card_number = normalize_card_number(card.card_number) if card.card_number else None

    series = parse_series_number(card_number) if card_number else None
    if series:
        # シリーズ番号(DN-001 / NM-001 / NX-001 / 忍-001 等)は
        # プレフィックス指定でタイトルから拾って番号を比較する
        prefix, num = series
        found = extract_series_number(title, prefix)
        title_number = f"{prefix}-{found}" if found is not None else None
    else:
        title_number = extract_card_number(title)
        if title_number is None and card_number is not None and "/" not in card_number:
            # カードダス等のスラッシュ無し番号は No.xx 形式で拾う
            title_number = extract_carddass_number(title)

    title_set = extract_set_code(title)
    card_set = card.set_code.lower() if card.set_code else None

    if card_number is not None and title_number is not None:
        if title_number != card_number:
            return CONF_NONE  # 番号が明示的に違う = 別カード
        if card_set and title_set:
            return CONF_HIGH if title_set == card_set else CONF_NONE
        if card_set is None and title_set is None:
            # セット指定なしのカード(カードダス等)は番号一致を high 扱い
            return CONF_HIGH
        return CONF_MEDIUM  # 番号は一致、セットは片方に無くて確認できない

    # 番号で判定できない場合は名前のみ
    nd = name_dict or NameDict()
    if nd.title_contains_name(title, card.name_ja, card.name_en):
        if card_number is not None and title_number is None:
            return CONF_LOW  # 番号を持つカードなのにタイトルから取れない → 弱い一致
        if card_number is None:
            # 番号を持たない商品(未開封BOX・プロモ等のキーワード監視)は
            # 名前の完全一致が取り得る最良の判定なので medium 扱い
            return CONF_MEDIUM
    return CONF_NONE
