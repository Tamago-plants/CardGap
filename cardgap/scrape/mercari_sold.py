"""メルカリの売り切れ(SOLD)出品スクレイパー。

目的: 「メルカリ内で実際に売れている物と売れた価格」を集める。
eBay相場が使えない期間は、この売却データがメルカリ内相場(売却中央値)の
元データになり、騰落・売れ筋ランキング・割安検出の基盤になる。

実装は販売中スクレイパー(mercari.py)の完全な再利用:
検索URLの status を sold_out にし、並びを新着順にするだけで、
セル構造・価格の取り出し方(aria-labelの円価格)は同一。

注意: 売却日時は検索結果に含まれないため、DB側で「初観測日時」を
売却日の近似として扱う(1日4回巡回なので誤差は数時間)。
"""

from __future__ import annotations

from urllib.parse import quote_plus

from ..config import Config
from . import ParsedPage, browser
from .mercari import (  # 再利用: セル構造は販売中と同一
    BASE_URL,
    SCROLL_ROUNDS,
    WAIT_SELECTOR,
    build_query,
    parse_search_html,
)

__all__ = [
    "SOURCE", "WAIT_SELECTOR", "SCROLL_ROUNDS",
    "build_query", "build_search_url", "parse_search_html", "fetch_query",
]

SOURCE = "mercari_sold"


def build_search_url(query: str) -> str:
    """売り切れのみ・新着順。直近に売れた物から順に観測する。"""
    return (
        f"{BASE_URL}/search?keyword={quote_plus(query)}"
        "&status=sold_out&sort=created_time&order=desc"
    )


def fetch_query(query: str, cfg: Config) -> ParsedPage:
    """検索クエリ1件分を browser 経由で取得してパースする(CLI/単発確認用)。"""
    url = build_search_url(query)
    with browser.new_page(cfg) as page:
        html = browser.fetch_html(
            page, url, cfg, wait_selector=WAIT_SELECTOR, source=SOURCE, query=query,
            scroll_rounds=SCROLL_ROUNDS,
        )
    return parse_search_html(html, raw_query=query)
