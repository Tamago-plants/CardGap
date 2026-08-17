"""タイトル文字列の正規化。日英タイトルを比較する前に必ず通す。"""

from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """NFKC正規化(全角→半角等) + 小文字化 + 空白圧縮。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = _WS_RE.sub(" ", text).strip()
    return text


# シリーズ番号(ナルト系): DN-001 / NM-001 / NX-001 / 忍-001 のような
# 「プレフィックス + 数字」形式。プレフィックスは英字1〜4文字 or 漢字かな1〜2文字
_SERIES_NUMBER_RE = re.compile(r"^([a-z]{1,4}|[぀-ヿ一-鿿]{1,2})\s*[-‐‑–—−ー]?\s*(\d{1,4})$")


def parse_series_number(num: str) -> tuple[str, int] | None:
    """'DN-001' / 'dn001' / '忍-001' → ('dn', 1) / ('忍', 1)。違う形式なら None。"""
    m = _SERIES_NUMBER_RE.fullmatch(normalize(num))
    if m:
        return m.group(1), int(m.group(2))
    return None


def normalize_card_number(num: str) -> str | None:
    """カード番号を比較可能な正規形にする(先頭ゼロ除去・小文字化)。

    '087/100' → '87/100'、'No.25' → '25'、'DN-001' → 'dn-1'、'忍-001' → '忍-1'
    """
    num = normalize(num)
    m = re.fullmatch(r"(\d{1,3})\s*/\s*(\d{1,3})", num)
    if m:
        return f"{int(m.group(1))}/{int(m.group(2))}"
    # 'No.25' 形式はシリーズ番号より先に判定する('no 25' を no シリーズ扱いしない)
    m = re.fullmatch(r"(?:no\.?\s*)?(\d{1,4})", num)
    if m:
        return str(int(m.group(1)))
    series = parse_series_number(num)
    if series:
        return f"{series[0]}-{series[1]}"
    return None
