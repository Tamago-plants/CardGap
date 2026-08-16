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


def normalize_card_number(num: str) -> str | None:
    """'087/100' → '87/100'、'25' → '25' のように先頭ゼロを落として比較可能にする。"""
    num = normalize(num)
    m = re.fullmatch(r"(\d{1,3})\s*/\s*(\d{1,3})", num)
    if m:
        return f"{int(m.group(1))}/{int(m.group(2))}"
    m = re.fullmatch(r"(?:no\.?\s*)?(\d{1,4})", num)
    if m:
        return str(int(m.group(1)))
    return None
