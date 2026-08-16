"""アプリ全体で使うデータ型。スクレイパー/マッチング/損益計算はこの型でやり取りする。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# マッチング確度
CONF_HIGH = "high"      # カード番号 + セット記号 (+ PSAグレード指定があれば一致)
CONF_MEDIUM = "medium"  # カード番号のみ一致
CONF_LOW = "low"        # カード名のみ一致
CONF_NONE = "none"      # 不一致(集計から除外)

# 相場信頼度
RELIABILITY_OK = "ok"
RELIABILITY_LOW = "low"  # 直近30日の落札件数が閾値未満


@dataclass
class Card:
    """watchlist.csv 1行 = 監視対象カード1件。cards テーブルに対応。"""

    category: str               # 'pokemon' | 'naruto' | ...
    name_ja: str
    name_en: str
    set_code: Optional[str]     # 例: 's12a'。ナルト系カードダスは None 可
    card_number: Optional[str]  # 例: '201/190' や '087'(カードダスのNo.)
    psa_grade: Optional[int]    # None = 生カード(raw)
    enabled: bool = True
    id: Optional[int] = None

    def display_name(self) -> str:
        parts = [self.name_ja]
        if self.card_number:
            parts.append(self.card_number)
        if self.set_code:
            parts.append(self.set_code)
        if self.psa_grade:
            parts.append(f"PSA{self.psa_grade}")
        return " ".join(parts)


@dataclass
class EbaySoldListing:
    title: str
    price_usd: float            # 落札価格(本体)
    shipping_usd: float         # 送料。不明/送料込みは 0
    sold_at: Optional[str]      # ISO日付 'YYYY-MM-DD'。取れなければ None
    image_url: Optional[str]
    listing_url: str
    psa_grade: Optional[int] = None  # タイトルから抽出
    raw_query: str = ""
    card_id: Optional[int] = None
    match_confidence: str = CONF_NONE

    @property
    def total_usd(self) -> float:
        return self.price_usd + self.shipping_usd


@dataclass
class MercariListing:
    title: str
    price_jpy: int
    condition: Optional[str]    # 商品状態(検索一覧から取れない場合 None)
    image_url: Optional[str]
    listing_url: str
    listed_at: Optional[str] = None
    raw_query: str = ""
    card_id: Optional[int] = None
    match_confidence: str = CONF_NONE


@dataclass
class SnkrdunkListing:
    product_name: str
    min_price_jpy: int
    product_url: str
    image_url: Optional[str] = None
    raw_query: str = ""
    card_id: Optional[int] = None
    match_confidence: str = CONF_NONE


@dataclass
class MarketStats:
    """あるカードの eBay 直近N日の落札統計(送料込み総額USDベース)。"""

    median_usd: float
    count: int
    min_usd: float
    max_usd: float
    reliability: str  # RELIABILITY_OK / RELIABILITY_LOW


@dataclass
class ProfitResult:
    revenue_jpy: float       # 想定売上(為替マージン控除後)
    ebay_fees_jpy: float
    ship_out_jpy: float
    buy_total_jpy: float     # 仕入価格 + 仕入手数料 + 仕入送料
    profit_jpy: float
    profit_rate: float
    fx_rate: float           # 使用した USD/JPY 生レート


@dataclass
class Deal:
    """ダッシュボード/通知に出す1案件 = 仕入れ候補1件 + eBay相場 + 損益。"""

    card: Card
    source: str                  # 'mercari' | 'snkrdunk'
    source_listing_id: int
    title: str
    buy_price_jpy: int
    listing_url: str
    image_url: Optional[str]
    confidence: str
    stats: MarketStats
    profit: ProfitResult


@dataclass
class ScrapeStats:
    """1ソース1回分のスクレイプ結果サマリ。ログ/Discord通知用。"""

    source: str
    queries_total: int = 0
    queries_failed: int = 0
    items_found: int = 0
    parse_failures: int = 0
    errors: list[str] = field(default_factory=list)
    # クエリ自体が失敗したカードの id。メルカリの在庫失効処理
    # (deactivate_stale_mercari)で「取得失敗＝売切れ」と誤判定しないために使う
    failed_card_ids: list[int] = field(default_factory=list)
