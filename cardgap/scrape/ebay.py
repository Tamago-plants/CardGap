"""eBay Sold(落札済み)検索結果のスクレイパー。

相場計算の元データとなる「実際に売れた価格」を取るため、検索URLに
LH_Sold=1 & LH_Complete=1 を付けて落札済みのみを対象にする。

注意: eBay の DOM は変わりやすい。パースが壊れた場合(errors に
"no items parsed" が出る等)は、config.yaml の scrape.debug_html_dir に
ディレクトリを指定して取得HTMLを保存し、実際のHTMLを見ながら本モジュールの
セレクタを直すこと。
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

from ..config import Config
from ..matching.extract import extract_psa_grade
from ..models import Card, EbaySoldListing
from . import ParsedPage, browser

logger = logging.getLogger(__name__)

SOURCE = "ebay"

# 検索結果1件分の <li>。fetch_html() の描画待ちにも使う
# 新旧レイアウト両対応で待つ(s-item=旧、s-card=新カード型SRP)。どちらも無ければ
# fetch_html が即座にHTMLを返し「0件+エラー」として可視化される
WAIT_SELECTOR = "li.s-item, li.s-card, ul.srp-results"

# 例: "$1,234.56"。"$300.00 to $350.00" のレンジは最初のマッチ = 下限を採用する
_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)")

# 例: "Sold Oct 12, 2025" / "Sold  Jul 20, 2026"(空白が2つ入ることがある)
_SOLD_DATE_RE = re.compile(r"sold\s+([A-Za-z]{3}\s+\d{1,2},\s*\d{4})", re.IGNORECASE)

# 検索結果一覧の先頭に入る広告プレースホルダのタイトル(実データではないのでスキップ)
_PLACEHOLDER_TITLE = "Shop on eBay"


def build_query(card: Card) -> str:
    """watchlist カード → eBay 検索クエリ。英名 + Japanese + セット記号 + カード番号 (+ PSA)。

    対象は日本語版のみのため 'Japanese' を必ず入れる(英語版はコレクター番号が
    同一でも別相場。日本語版の出品はほぼ確実にタイトルに Japanese を含む)。
    """
    # シリーズ監視(DN-* 等)はプレフィックスのみで検索し、シリーズ全体を1クエリで拾う。
    # 漢字プレフィックス(忍 等)は海外セラーのタイトルに含まれずヒットを狭めるため
    # クエリからは外す(番号の絞り込みはマッチング側で行われる)
    number = card.query_number()
    if number and not number.isascii():
        number = None
    parts = [card.name_en, "Japanese", card.set_code, number]
    query = " ".join(p for p in parts if p)
    if card.psa_grade:
        query += f" PSA {card.psa_grade}"
    return query


def build_search_url(query: str) -> str:
    """Sold + Completed 絞り込み・1ページ120件表示の検索URLを組み立てる。"""
    return (
        "https://www.ebay.com/sch/i.html"
        f"?_nkw={urllib.parse.quote_plus(query)}"
        "&LH_Sold=1&LH_Complete=1&_ipg=120"
    )


def _parse_price(text: str) -> Optional[float]:
    """'$1,234.56' 形式の金額を float で返す。レンジ表記は下限。見つからなければ None。"""
    m = _PRICE_RE.search(text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _parse_sold_date(li) -> Optional[str]:
    """'Sold Oct 12, 2025' 系のキャプションから ISO 日付を返す。取れなければ None。"""
    for sel in (".s-item__caption", "span.POSITIVE", ".s-item__title--tag"):
        for el in li.select(sel):
            m = _SOLD_DATE_RE.search(el.get_text(" ", strip=True))
            if not m:
                continue
            # "Jul  20, 2026" のような余分な空白を潰してからパースする
            date_text = " ".join(m.group(1).split())
            try:
                return datetime.strptime(date_text, "%b %d, %Y").strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


def _parse_item(li, raw_query: str) -> Optional[EbaySoldListing]:
    """li.s-item 1件をパースする。プレースホルダは None、必須要素の欠落は例外。"""
    title_el = li.select_one(".s-item__title")
    title = title_el.get_text(" ", strip=True) if title_el else ""
    if title == _PLACEHOLDER_TITLE:
        return None  # 一覧先頭の広告枠。実データではないので黙ってスキップ
    if not title:
        raise ValueError("title not found")

    price_el = li.select_one(".s-item__price")
    if price_el is None:
        raise ValueError("price element not found")
    price_usd = _parse_price(price_el.get_text(" ", strip=True))
    if price_usd is None:
        raise ValueError(f"unparsable price: {price_el.get_text(strip=True)!r}")

    # 送料。"Free shipping" / "送料無料" / 要素なし はすべて 0.0 扱い
    shipping_usd = 0.0
    ship_el = li.select_one(".s-item__shipping, .s-item__logisticsCost")
    if ship_el is not None:
        shipping_usd = _parse_price(ship_el.get_text(" ", strip=True)) or 0.0

    link_el = li.select_one("a.s-item__link")
    if link_el is None or not link_el.get("href"):
        raise ValueError("listing link not found")
    # "?" 以降はトラッキングパラメータなので落とす(URLの重複排除のため)
    listing_url = str(link_el["href"]).split("?", 1)[0]

    image_url: Optional[str] = None
    img_el = li.select_one("img")
    if img_el is not None:
        image_url = img_el.get("src") or img_el.get("data-src") or None

    # タイトルから PSA グレードを抽出。8.5 等の半グレードは int にできないため None のまま
    grade = extract_psa_grade(title)
    psa_grade = int(grade) if grade is not None and float(grade).is_integer() else None

    return EbaySoldListing(
        title=title,
        price_usd=price_usd,
        shipping_usd=shipping_usd,
        sold_at=_parse_sold_date(li),
        image_url=image_url,
        listing_url=listing_url,
        psa_grade=psa_grade,
        raw_query=raw_query,
    )


def parse_search_html(html: str, raw_query: str = "") -> ParsedPage:
    """検索結果HTML → ParsedPage。純関数(ネットワーク・Playwright 非依存)。

    1件のパース失敗で全体を止めず、parse_failures / errors に積んで残りを返す。
    """
    page = ParsedPage()
    soup = BeautifulSoup(html, "lxml")
    for li in soup.select("li.s-item"):
        try:
            item = _parse_item(li, raw_query)
            if item is not None:
                page.items.append(item)
        except Exception as e:
            page.parse_failures += 1
            page.errors.append(f"ebay item parse failed: {e}")
    if not page.items and html.strip():
        page.errors.append("no items parsed (bot検知またはDOM変更の可能性)")
    return page


def fetch_query(query: str, cfg: Config) -> ParsedPage:
    """検索クエリ1件分を取得してパースする。

    1日の実行上限(scrape.max_ebay_queries_per_day)の管理は呼び出し側で行う。
    """
    url = build_search_url(query)
    logger.info("ebay fetch: %s", url)
    with browser.new_page(cfg) as page:
        html = browser.fetch_html(
            page, url, cfg, wait_selector=WAIT_SELECTOR, source=SOURCE, query=query
        )
    return parse_search_html(html, raw_query=query)
