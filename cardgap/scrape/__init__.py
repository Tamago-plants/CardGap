"""スクレイパー共通の型と規約。

各スクレイパーモジュール(ebay / mercari / snkrdunk)は次の関数を必ず公開する:

  SOURCE: str                                   # 'ebay' | 'mercari' | 'snkrdunk'
  build_query(card: Card) -> str                # watchlist カード → 検索クエリ文字列
  build_search_url(query: str) -> str           # クエリ → 検索URL
  parse_search_html(html: str, raw_query: str = "") -> ParsedPage
      # 純関数。ネットワーク・Playwright に依存しない(フィクスチャでテストする)
  fetch_query(query: str, cfg: Config) -> ParsedPage
      # browser.fetch_html() で検索ページを取得して parse_search_html に渡す

parse_search_html は「一覧のうち1件のパースに失敗しても残りは返す」こと。
失敗件数は ParsedPage.parse_failures に積む(握りつぶさない)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedPage:
    items: list[Any] = field(default_factory=list)   # models の各 Listing 型
    parse_failures: int = 0
    errors: list[str] = field(default_factory=list)  # 失敗の内訳(ログ/通知用)
