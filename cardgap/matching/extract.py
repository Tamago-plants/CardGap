"""タイトルからカード番号・セット記号・PSAグレードを抽出する。

日英どちらのタイトルにも同じ関数を使う(先に normalize() を通す前提)。
"""

from __future__ import annotations

import re
from typing import Optional

from .normalize import normalize

# 注意: \b は使わない。Python の \w は漢字・かなを含むため、「PSA10鑑定済」の
# ように直後に日本語が続くと \b が境界にならず取りこぼす(メルカリ/スニダンの
# タイトルは空白なしの日本語連結が普通)。ASCII 英数字だけを「語」とみなす
# lookaround で境界判定する(normalize() 済みの小文字前提)。

# 例: 201/190, 087/100 (全角スラッシュはNFKCで半角化される)
# lookbehind は数字・ドット・スラッシュのみブロック(「リザードンex201/165」の
# ような英字直結は正当なタイトルなので許す。日付 2023/12/01 は数字連続で弾かれる)
_CARD_NUMBER_RE = re.compile(r"(?<![0-9./])(\d{1,3})\s*/\s*(\d{1,3})(?![0-9/])")

# 例: s12a, sv4a, sm12b, xy7, bw9 (ポケカの拡張セット記号)
# 誤検知を避けるため数字必須・境界必須にしている
_SET_CODE_RE = re.compile(r"(?<![a-z0-9])(sv|s|sm|xy|bw)(\d{1,2})([a-z]{0,2})(?![a-z0-9])")

# 例: PSA 10 / PSA10 / psa-9 / PSA:8.5 / PSA10鑑定済
_PSA_RE = re.compile(r"(?<![a-z0-9])psa\s*[-:]?\s*(10|[1-9](?:\.5)?)(?![0-9.])")

# カードダス等の「No.25」形式(スラッシュ番号が無い場合のフォールバック)
_NO_RE = re.compile(r"(?<![a-z0-9])no\.?\s*(\d{1,4})(?![0-9])")


def extract_card_number(title: str) -> Optional[str]:
    """'201/190' 形式を正規化して返す(先頭ゼロ除去)。無ければ None。"""
    t = normalize(title)
    m = _CARD_NUMBER_RE.search(t)
    if m:
        return f"{int(m.group(1))}/{int(m.group(2))}"
    return None


def extract_carddass_number(title: str) -> Optional[str]:
    """'No.25' 形式の番号。カードダス系のフォールバック用。"""
    t = normalize(title)
    m = _NO_RE.search(t)
    if m:
        return str(int(m.group(1)))
    return None


def extract_set_code(title: str) -> Optional[str]:
    t = normalize(title)
    m = _SET_CODE_RE.search(t)
    if m:
        return f"{m.group(1)}{int(m.group(2))}{m.group(3)}"
    return None


def extract_psa_grade(title: str) -> Optional[float]:
    """PSAグレード。整数グレードでも 8.5 のような半グレードでも float で返す。"""
    t = normalize(title)
    m = _PSA_RE.search(t)
    if m:
        return float(m.group(1))
    return None
