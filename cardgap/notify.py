"""Discord Webhook 通知。

検出と通知のみ。自動購入・自動入札は行わない。

pipeline.run_daily() の最後に send_notifications() が呼ばれ、閾値を満たした
新規案件(未通知・未無視)を embed にして Discord Webhook へ POST する。
一度通知した出品は notified_deals テーブルに記録し、再通知しない。
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Optional

import requests

from . import db
from .config import Config
from .models import CONF_HIGH, CONF_MEDIUM, RELIABILITY_OK, Deal, ScrapeStats

logger = logging.getLogger(__name__)

# Discord 側の embed 上限は 10件/メッセージ。設定値がそれを超えても 10 で頭打ち
_DISCORD_MAX_EMBEDS = 10

# 仕入元の表示名(embed タイトル用)
_SOURCE_LABELS = {"mercari": "メルカリ", "snkrdunk": "スニダン"}

# embed の色(利益率で段階分け)
_COLOR_RATE_50 = 0xE74C3C  # 利益率 50% 以上: 赤
_COLOR_RATE_30 = 0xE67E22  # 利益率 30% 以上: 橙
_COLOR_DEFAULT = 0x2ECC71  # それ未満: 緑


def filter_deals_for_notification(
    cfg: Config, conn: sqlite3.Connection, deals: list[Deal]
) -> list[Deal]:
    """通知対象の案件だけに絞り込む。

    条件: 利益額・利益率が閾値以上 / 相場信頼度 ok / confidence が high or medium
          / 無視リストに無い / 通知済みでない。
    """
    min_profit_jpy = float(cfg.get("threshold.min_profit_jpy", 5000))
    min_profit_rate = float(cfg.get("threshold.min_profit_rate", 0.20))
    result: list[Deal] = []
    for d in deals:
        if d.profit.profit_jpy < min_profit_jpy:
            continue
        if d.profit.profit_rate < min_profit_rate:
            continue
        if d.stats.reliability != RELIABILITY_OK:
            continue
        if d.confidence not in (CONF_HIGH, CONF_MEDIUM):
            continue
        if db.is_ignored(conn, d.listing_url):
            continue
        if db.is_notified(conn, d.listing_url):
            continue
        result.append(d)
    return result


def _embed_color(profit_rate: float) -> int:
    """利益率に応じた embed の色。"""
    if profit_rate >= 0.50:
        return _COLOR_RATE_50
    if profit_rate >= 0.30:
        return _COLOR_RATE_30
    return _COLOR_DEFAULT


def build_deal_embed(deal: Deal) -> dict[str, Any]:
    """案件1件を Discord embed(dict)に変換する。"""
    source_label = _SOURCE_LABELS.get(deal.source, deal.source)
    embed: dict[str, Any] = {
        "title": f"{deal.card.display_name()} [{source_label}]",
        "url": deal.listing_url,
        "color": _embed_color(deal.profit.profit_rate),
        "fields": [
            {"name": "仕入価格", "value": f"¥{deal.buy_price_jpy:,}", "inline": True},
            {
                "name": "eBay相場中央値",
                "value": f"${deal.stats.median_usd:,.2f} ({deal.stats.count}件)",
                "inline": True,
            },
            {"name": "実質利益", "value": f"¥{round(deal.profit.profit_jpy):,}", "inline": True},
            {"name": "利益率", "value": f"{deal.profit.profit_rate * 100:.1f}%", "inline": True},
            {"name": "confidence", "value": deal.confidence, "inline": True},
        ],
    }
    if deal.image_url:
        embed["thumbnail"] = {"url": deal.image_url}
    return embed


def build_failure_summary(scrape_stats: list[ScrapeStats]) -> Optional[str]:
    """スクレイプ失敗のサマリ文字列。失敗が1件も無ければ None。

    例: '⚠ スクレイプ失敗: ebay クエリ失敗2/50, パース失敗3件'
    """
    parts: list[str] = []
    for s in scrape_stats:
        segs: list[str] = []
        if s.queries_failed > 0:
            segs.append(f"クエリ失敗{s.queries_failed}/{s.queries_total}")
        if s.parse_failures > 0:
            segs.append(f"パース失敗{s.parse_failures}件")
        if segs:
            parts.append(f"{s.source} " + ", ".join(segs))
    if not parts:
        return None
    return "⚠ スクレイプ失敗: " + " / ".join(parts)


def _post(webhook: str, payload: dict[str, Any]) -> bool:
    """Webhook へ1メッセージ POST。2xx なら True、例外/非2xx は logger.error して False。"""
    try:
        resp = requests.post(webhook, json=payload, timeout=15)
    except Exception as e:
        logger.error("Discord 送信に失敗: %s", e)
        return False
    if not 200 <= resp.status_code < 300:
        logger.error("Discord 送信に失敗: HTTP %s", resp.status_code)
        return False
    return True


def send_notifications(
    cfg: Config,
    conn: sqlite3.Connection,
    deals: list[Deal],
    scrape_stats: list[ScrapeStats],
) -> bool:
    """通知対象の案件とスクレイプ失敗サマリを Discord へ送る。

    - Webhook 未設定なら何もせず True(通知はオプション機能。エラーではない)
    - 案件0件でも失敗サマリがあれば content のみ送る。案件0・失敗0なら送らず True
    - 送信成功(2xx)したメッセージに含めた案件のみ mark_notified する
    """
    webhook = cfg.discord_webhook_url()
    if not webhook:
        logger.info("Discord webhook 未設定のため通知をスキップ")
        return True

    targets = filter_deals_for_notification(cfg, conn, deals)
    summary = build_failure_summary(scrape_stats)

    if not targets and summary is None:
        logger.info("通知対象0件・スクレイプ失敗なし。送信しない")
        return True

    content = f"CardGap: 本日の検出 {len(targets)}件"
    if summary:
        content += "\n" + summary

    per_message = min(
        _DISCORD_MAX_EMBEDS, int(cfg.get("discord.max_deals_per_message", _DISCORD_MAX_EMBEDS))
    )
    per_message = max(1, per_message)

    # 1通目のみ content を載せ、embeds は per_message 件ずつ分割する
    batches: list[tuple[Optional[str], list[Deal]]] = []
    if targets:
        for i in range(0, len(targets), per_message):
            batches.append((content if i == 0 else None, targets[i : i + per_message]))
    else:
        batches.append((content, []))  # 失敗サマリのみ

    for msg_content, batch in batches:
        payload: dict[str, Any] = {}
        if msg_content:
            payload["content"] = msg_content
        if batch:
            payload["embeds"] = [build_deal_embed(d) for d in batch]
        if not _post(webhook, payload):
            return False
        for d in batch:
            db.mark_notified(conn, d.source, d.listing_url)
        conn.commit()

    logger.info("Discord 通知完了: %d件 (%dメッセージ)", len(targets), len(batches))
    return True


def send_test_message(cfg: Config) -> bool:
    """疎通確認用のテストメッセージを送る。Webhook 未設定なら False。"""
    webhook = cfg.discord_webhook_url()
    if not webhook:
        logger.error("Discord webhook が未設定です(DISCORD_WEBHOOK_URL か config.yaml で設定)")
        return False
    return _post(webhook, {"content": "CardGap 疎通テスト"})
