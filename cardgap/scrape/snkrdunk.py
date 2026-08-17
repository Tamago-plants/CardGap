"""スニーカーダンク(スニダン)検索ページのスクレイパー(仕入れ側の価格取得)。

注意:
- スニダンは商品マスタが整理されており(1商品 = 1カード型番)、型番マッチ精度が高い。
  ただしDOMは変更されやすいため、パースが壊れたら config.yaml の
  scrape.debug_html_dir に取得HTMLを保存して実際のセレクタを調査すること。
- 検索にはトレカ以外(スニーカー・アパレル等)もヒットするため、href に
  "/trading-cards/" を含むリンクだけを商品カードとして扱い、それ以外は除外する。
- 一覧に表示される価格は「最安出品価格」。出品が無い商品は "--" や "未定" と
  表示されるのでスキップする(エラーではなく出品なし扱い)。
- 個人利用の低頻度アクセス厳守(取得は必ず browser.fetch_html 経由。
  polite_sleep のランダムディレイを挟む)。
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag

from ..config import Config
from ..models import Card, SnkrdunkListing
from . import ParsedPage, browser

logger = logging.getLogger(__name__)

SOURCE = "snkrdunk"
BASE_URL = "https://snkrdunk.com"

# SPAだがセレクタ待ちはしない。トレカのヒットが0件の検索でタイムアウトしてしまうため、
# fetch_html() の wait_selector=None フォールバック(固定時間の描画待ち)に任せる
WAIT_SELECTOR: Optional[str] = None

# 商品カード = トレカ商品ページへのリンク。スニーカー等("/sneakers/" 等)はここで除外される
_CARD_SELECTOR = 'a[href*="/trading-cards/"]'

# 商品名要素(class 名に name を含む p)。取れなければ img alt にフォールバック
_NAME_SELECTOR = 'p[class*="name"]'

# 例: '¥55,000' / '￥ 1,200'(全角円記号・空白入りも許容)
_PRICE_RE = re.compile(r"[¥￥]\s*([\d,]+)")

# 出品なしの価格表示。この商品はスキップする(エラー扱いにしない)
_NO_STOCK_MARKERS = ("--", "未定")


def build_query(card: Card) -> str:
    """watchlist カード → スニダン検索クエリ文字列。

    日本語名 + カード番号(あれば)。psa_grade はクエリに付けない:
    スニダンでは PSA鑑定品が生カードとは別の商品マスタとして登録されており、
    'PSA10' を足すと生カード側の商品マスタにヒットしなくなる等クエリが不安定になる。
    グレードの絞り込みはマッチング側(matching.engine)の PSAグレード条件に任せる。
    """
    parts = [card.name_ja]
    number = card.query_number()  # シリーズ監視(DN-*)はプレフィックスのみ
    if number:
        parts.append(number)
    return " ".join(parts)


def build_search_url(query: str) -> str:
    """検索URL。キーワードのみ(スニダンの検索結果は商品マスタ単位で返る)。"""
    return f"{BASE_URL}/search?keyword={quote_plus(query)}"


def _parse_card(card: Tag) -> Optional[SnkrdunkListing]:
    """商品カード1件 → SnkrdunkListing。出品なし(価格 "--"/"未定")は None を返す。

    必須要素(商品名・価格)が欠けていれば ValueError。
    """
    href = card.get("href")
    if not href:
        raise ValueError("商品リンクの href が空")
    # トラッキング用クエリ("?"以降)は落として正規化(URLがDBの一意キーのため)
    product_url = urljoin(BASE_URL, str(href)).split("?", 1)[0]

    img = card.select_one("img")

    # 商品名: 商品名要素を優先、無ければ img の alt
    product_name = ""
    name_el = card.select_one(_NAME_SELECTOR)
    if name_el is not None:
        product_name = name_el.get_text(strip=True)
    if not product_name and img is not None and img.get("alt"):
        product_name = str(img["alt"]).strip()
    if not product_name:
        raise ValueError("商品名が取れない(商品名要素 / img alt とも空)")

    text = card.get_text(" ", strip=True)
    m = _PRICE_RE.search(text)
    if m is None:
        if any(marker in text for marker in _NO_STOCK_MARKERS):
            return None  # 出品なし商品。エラーではないので黙ってスキップ
        raise ValueError("価格表示(¥xxx)が見つからない")
    min_price_jpy = int(m.group(1).replace(",", ""))

    image_url = str(img["src"]) if img is not None and img.get("src") else None

    return SnkrdunkListing(
        product_name=product_name,
        min_price_jpy=min_price_jpy,
        product_url=product_url,
        image_url=image_url,
    )


def parse_search_html(html: str, raw_query: str = "") -> ParsedPage:
    """検索結果HTML → ParsedPage。純関数(ネットワーク・Playwright 非依存)。

    1件のパース失敗で全体を落とさず、残りは返す。失敗数は parse_failures に積み、
    内訳を errors に残す(握りつぶさない)。出品なし("--"/"未定")は失敗に数えない。
    """
    page = ParsedPage()
    soup = BeautifulSoup(html, "lxml")
    for card in soup.select(_CARD_SELECTOR):
        try:
            item = _parse_card(card)
        except Exception as e:
            page.parse_failures += 1
            page.errors.append(f"[{SOURCE}] 商品カードのパース失敗 ({raw_query}): {e}")
            continue
        if item is None:
            continue  # 出品なし商品(価格 "--"/"未定")
        item.raw_query = raw_query
        page.items.append(item)

    if not page.items:
        # 0件はDOM変更・bot検知の兆候かもしれないので警告として残す(出品なしの可能性もある)
        msg = f"[{SOURCE}] 商品を1件も抽出できず: query={raw_query!r} (出品なし/DOM変更/ブロックの可能性)"
        logger.warning(msg)
        page.errors.append(msg)
    return page


def fetch_query(query: str, cfg: Config) -> ParsedPage:
    """検索クエリ1件分を browser 経由で取得してパースする(CLI/単発確認用)。"""
    url = build_search_url(query)
    with browser.new_page(cfg) as page:
        html = browser.fetch_html(
            page, url, cfg, wait_selector=WAIT_SELECTOR, source=SOURCE, query=query
        )
    return parse_search_html(html, raw_query=query)
