"""メルカリ検索ページのスクレイパー(仕入れ側の価格取得)。

注意:
- メルカリはSPAでDOM変更が頻繁。data-testid ベースのセレクタで拾い、壊れたら
  config.yaml の scrape.debug_html_dir に取得HTMLを保存して調査する。
- ログイン必須ページ(取引画面・マイページ等)は対象外。公開の検索結果のみ扱う。
- 個人利用の低頻度アクセス厳守(取得は必ず browser.fetch_html 経由。
  polite_sleep のランダムディレイを挟む)。

検索一覧からは商品状態・出品日時が取れないため condition / listed_at は None。
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag

from ..config import Config
from ..models import Card, MercariListing
from . import ParsedPage, browser

logger = logging.getLogger(__name__)

SOURCE = "mercari"
BASE_URL = "https://jp.mercari.com"

# 検索結果の商品セル。SPAなので fetch 時はこれが現れるまで待つ
WAIT_SELECTOR = 'li[data-testid="item-cell"]'

# 遅延読み込みの描画を進めるためのスクロール回数(1回ごとに1画面分)。
# 検索は価格昇順なので先頭=最安だが、スクロールするほど取得件数が増える
SCROLL_ROUNDS = 3

# 例: '¥39,800' / '￥ 1,200'(全角円記号・空白入りも許容)
_PRICE_RE = re.compile(r"[¥￥]\s*([\d,]+)")

# aria-label 内の円価格。例: '〜の画像 300円 US$1.98' → 300
# (海外IPからのアクセスでは表示が外貨になるが、aria-label には円が残る)
_YEN_RE = re.compile(r"(\d[\d,]*)円")

# img alt の接尾辞(「〜のサムネイル」「〜の画像」等)を商品名から除く
_ALT_SUFFIX_RE = re.compile(r"の(サムネイル|画像)$")


def build_query(card: Card) -> str:
    """watchlist カード → メルカリ検索クエリ文字列。

    日本語名 + カード番号(あれば)。PSA指定があれば 'PSA10' を付ける
    (日本の出品は 'PSA 10' より空白なしの 'PSA10' 表記が多い)。
    """
    parts = [card.name_ja]
    number = card.query_number()  # シリーズ監視(DN-*)はプレフィックスのみ
    if number:
        parts.append(number)
    if card.psa_grade:
        parts.append(f"PSA{card.psa_grade}")
    return " ".join(parts)


def build_search_url(query: str) -> str:
    """検索URL。販売中のみ(status=on_sale)・価格昇順で、安い仕入候補を先頭に集める。"""
    return (
        f"{BASE_URL}/search?keyword={quote_plus(query)}"
        "&status=on_sale&sort=price&order=asc"
    )


def _extract_price_jpy(cell: Tag, title: str) -> int | None:
    """セルから販売価格(円)を取り出す。

    重要: 海外IP(GitHub Actions等)からのアクセスではメルカリは価格を
    「US$1.98」のような外貨表示にするため、表示テキストに ¥ が無い。
    ただしサムネイルの aria-label には「〜の画像 300円 US$1.98」のように
    **円価格が含まれる**ので、まず aria-label の「N円」を最優先で拾う。

    次点は価格用要素(class/data-testid に price)の ¥ 表記(日本IP表示)。
    タイトルに「定価¥3,000」等の金額が入る出品があるため、セル全文の最初の
    ¥ を拾うのは最後の手段とし、タイトル文字列を除いたテキストで検索する。
    """
    for el in cell.select("[aria-label]"):
        m = _YEN_RE.search(str(el.get("aria-label", "")))
        if m:
            return int(m.group(1).replace(",", ""))
    price_el = cell.select_one('[data-testid*="price"], [class*="price" i]')
    if price_el is not None:
        m = _PRICE_RE.search(price_el.get_text(" ", strip=True))
        if m:
            return int(m.group(1).replace(",", ""))
    text = cell.get_text(" ", strip=True)
    if title:
        text = text.replace(title, " ")
    m = _PRICE_RE.search(text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _is_skeleton(cell: Tag) -> bool:
    """遅延読み込みの未描画プレースホルダか(merSkeleton)。

    画面外のセルは中身が空のスケルトンとして返るため、パース失敗ではなく
    「まだ描画されていないだけ」としてカウント対象外で読み飛ばす。
    """
    return cell.select_one(".merSkeleton") is not None and cell.select_one("img") is None


def _parse_cell(cell: Tag) -> MercariListing:
    """商品セル1件 → MercariListing。必須要素が欠けていれば ValueError。"""
    a = cell.select_one('a[href*="/item/"]')
    if a is None or not a.get("href"):
        raise ValueError("商品リンク a[href*='/item/'] が見つからない")
    # トラッキング用クエリ("?"以降)は落として正規化(URLがDBの一意キーのため)
    listing_url = urljoin(BASE_URL, str(a["href"])).split("?", 1)[0]

    img = cell.select_one("img")

    # 商品名: img の alt(接尾辞除去)を優先、無ければ thumbnail-item-name
    title = ""
    if img is not None and img.get("alt"):
        title = _ALT_SUFFIX_RE.sub("", str(img["alt"]).strip()).strip()
    if not title:
        name_el = cell.select_one('[data-testid="thumbnail-item-name"]')
        if name_el is not None:
            title = name_el.get_text(strip=True)
    if not title:
        raise ValueError("商品名が取れない(img alt / thumbnail-item-name とも空)")

    price_jpy = _extract_price_jpy(cell, title)
    if price_jpy is None:
        raise ValueError("価格表示(¥xxx)が見つからない")

    image_url = str(img["src"]) if img is not None and img.get("src") else None

    return MercariListing(
        title=title,
        price_jpy=price_jpy,
        condition=None,   # 検索一覧には商品状態が出ない
        image_url=image_url,
        listing_url=listing_url,
        listed_at=None,   # 検索一覧には出品日時が出ない
    )


def parse_search_html(html: str, raw_query: str = "") -> ParsedPage:
    """検索結果HTML → ParsedPage。純関数(ネットワーク・Playwright 非依存)。

    1件のパース失敗で全体を落とさず、残りは返す。失敗数は parse_failures に積み、
    内訳を errors に残す(握りつぶさない)。
    """
    page = ParsedPage()
    soup = BeautifulSoup(html, "lxml")
    for cell in soup.select(WAIT_SELECTOR):
        if _is_skeleton(cell):
            continue  # 未描画の遅延読み込みセル。失敗ではないので黙って飛ばす
        try:
            item = _parse_cell(cell)
        except Exception as e:
            page.parse_failures += 1
            page.errors.append(f"[{SOURCE}] セルのパース失敗 ({raw_query}): {e}")
            continue
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
            page, url, cfg, wait_selector=WAIT_SELECTOR, source=SOURCE, query=query,
            scroll_rounds=SCROLL_ROUNDS,
        )
    return parse_search_html(html, raw_query=query)
