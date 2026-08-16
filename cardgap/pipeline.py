"""日次バッチの本体。cron からは `python -m cardgap.pipeline` で呼ぶ。

流れ: watchlist取込 → 為替更新 → eBay/メルカリ/スニダン スクレイプ
      → 相場集計+損益計算(matches再構築) → Discord通知
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta
from importlib import import_module
from typing import Optional

from . import db, fx
from .config import Config, load_config
from .matching import load_name_dict, match_title
from .matching.names import NameDict
from .models import CONF_NONE, Card, Deal, ScrapeStats
from .profit import profit_for_source
from .scrape import browser
from .stats import compute_market_stats
from .watchlist import import_watchlist

logger = logging.getLogger(__name__)

SOURCES = ("ebay", "mercari", "snkrdunk")


def _item_title(item) -> str:
    return getattr(item, "title", None) or getattr(item, "product_name", "")


def _load_name_dicts(cfg: Config) -> dict[str, NameDict]:
    dicts: dict[str, NameDict] = {}
    for cat, spec in cfg.enabled_categories().items():
        csv_rel = (spec or {}).get("names_csv")
        if csv_rel:
            dicts[cat] = load_name_dict(cfg.resolve_path(csv_rel))
    return dicts


def _cards_for_source(cfg: Config, cards: list[Card], source: str) -> list[Card]:
    cats = cfg.enabled_categories()
    result = []
    for c in cards:
        if c.category not in cats:
            continue
        if source == "snkrdunk" and not (cats[c.category] or {}).get("snkrdunk", False):
            continue
        result.append(c)
    return result


def run_scrape(
    source: str,
    cfg: Config,
    conn: sqlite3.Connection,
    cards: Optional[list[Card]] = None,
    limit_queries: Optional[int] = None,
) -> ScrapeStats:
    """1ソース分のスクレイプ実行: クエリ生成→取得→パース→マッチング→DB保存。"""
    mod = import_module(f"cardgap.scrape.{source}")
    all_cards = cards if cards is not None else db.list_cards(conn)
    target_cards = _cards_for_source(cfg, all_cards, source)

    if source == "ebay":
        # 日次上限は scrape_runs の実績で管理する(同日に複数回実行しても
        # 合計 cap を超えない)。watchlist が cap より多い場合は累計消費数を
        # 開始オフセットにして順繰りに巡回し、後方のカードが飢えないようにする。
        cap = int(cfg.get("scrape.max_ebay_queries_per_day", 50))
        used_today, used_total = db.ebay_query_usage(conn)
        remaining = max(0, cap - used_today)
        limit = min(limit_queries, remaining) if limit_queries else remaining
        if limit <= 0:
            logger.warning(
                "eBay daily query cap reached (%d/%d today); skipping ebay scrape",
                used_today, cap,
            )
            target_cards = []
        elif target_cards:
            start = used_total % len(target_cards)
            target_cards = (target_cards * 2)[start : start + limit]
    else:
        if limit_queries:
            target_cards = target_cards[:limit_queries]

    name_dicts = _load_name_dicts(cfg)
    stats = ScrapeStats(source=source)
    run_id = db.start_scrape_run(conn, source)

    if target_cards:
        with browser.new_page(cfg) as page:
            for card in target_cards:
                query = mod.build_query(card)
                stats.queries_total += 1
                try:
                    url = mod.build_search_url(query)
                    html = browser.fetch_html(
                        page,
                        url,
                        cfg,
                        wait_selector=getattr(mod, "WAIT_SELECTOR", None),
                        source=source,
                        query=query,
                    )
                    parsed = mod.parse_search_html(html, raw_query=query)
                except Exception as e:
                    stats.queries_failed += 1
                    if card.id is not None:
                        stats.failed_card_ids.append(card.id)
                    stats.errors.append(f"[{source}] {query}: {e}")
                    logger.warning("scrape query failed [%s] %s: %s", source, query, e)
                    continue

                stats.parse_failures += parsed.parse_failures
                stats.errors.extend(parsed.errors[:3])

                nd = name_dicts.get(card.category)
                for item in parsed.items:
                    item.card_id = card.id
                    item.match_confidence = match_title(_item_title(item), card, nd)

                if source == "ebay":
                    db.insert_ebay_sold(conn, parsed.items)
                elif source == "mercari":
                    db.upsert_mercari(conn, parsed.items)
                elif source == "snkrdunk":
                    db.upsert_snkrdunk(conn, parsed.items)
                conn.commit()
                stats.items_found += len(parsed.items)

    db.finish_scrape_run(
        conn,
        run_id,
        queries_total=stats.queries_total,
        queries_failed=stats.queries_failed,
        items_found=stats.items_found,
        parse_failures=stats.parse_failures,
        notes="; ".join(stats.errors[:10]),
    )
    conn.commit()
    logger.info(
        "[%s] queries=%d failed=%d items=%d parse_failures=%d",
        source, stats.queries_total, stats.queries_failed,
        stats.items_found, stats.parse_failures,
    )
    return stats


def recompute_matches(
    cfg: Config, conn: sqlite3.Connection, fx_rate: Optional[float] = None
) -> list[Deal]:
    """DB内のデータだけで相場集計と損益計算をやり直し、matches を再構築する。"""
    if fx_rate is None:
        fx_rate = fx.get_usd_jpy(cfg, conn, refresh=False)
    lookback = int(cfg.get("scrape.ebay_lookback_days", 30))
    since = (date.today() - timedelta(days=lookback)).isoformat()
    min_count = int(cfg.get("threshold.min_sold_count_30d", 3))

    deals: list[Deal] = []
    for card in db.list_cards(conn):
        rows = db.ebay_sold_for_card(conn, card.id, since)
        market = compute_market_stats(
            [r["price_usd"] + r["shipping_usd"] for r in rows], min_count
        )
        if market is None:
            continue

        # サイトの価格推移チャート・日次ダイジェストの騰落計算用に蓄積する
        db.upsert_market_snapshot(
            conn,
            card_id=card.id,
            date=date.today().isoformat(),
            median_usd=market.median_usd,
            count=market.count,
            min_usd=market.min_usd,
            max_usd=market.max_usd,
            fx_rate=fx_rate,
        )

        buy_rows = [
            ("mercari", r)
            for r in conn.execute(
                "SELECT * FROM listings_mercari WHERE card_id = ? AND active = 1"
                " AND match_confidence != ?",
                (card.id, CONF_NONE),
            ).fetchall()
        ] + [
            ("snkrdunk", r)
            for r in conn.execute(
                "SELECT * FROM listings_snkrdunk WHERE card_id = ?"
                " AND match_confidence != ?",
                (card.id, CONF_NONE),
            ).fetchall()
        ]
        for source, row in buy_rows:
            price = row["price_jpy"] if source == "mercari" else row["min_price_jpy"]
            profit = profit_for_source(cfg, source, market.median_usd, fx_rate, price)
            deals.append(
                Deal(
                    card=card,
                    source=source,
                    source_listing_id=row["id"],
                    title=row["title"] if source == "mercari" else row["product_name"],
                    buy_price_jpy=int(price),
                    listing_url=row["listing_url"] if source == "mercari" else row["product_url"],
                    image_url=row["image_url"],
                    confidence=row["match_confidence"],
                    stats=market,
                    profit=profit,
                )
            )
    db.rebuild_matches(conn, deals)
    conn.commit()
    logger.info("matches rebuilt: %d deals", len(deals))
    return deals


def run_daily(cfg: Optional[Config] = None) -> None:
    cfg = cfg or load_config()
    logging.basicConfig(
        level=getattr(logging, str(cfg.get("app.log_level", "INFO")), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    conn = db.connect(cfg.db_path())
    try:
        n = import_watchlist(conn, cfg)
        logger.info("watchlist imported: %d cards", n)

        fx_rate = fx.get_usd_jpy(cfg, conn, refresh=True)

        started_at = db.utcnow()
        all_stats: list[ScrapeStats] = []
        for source in SOURCES:
            try:
                all_stats.append(run_scrape(source, cfg, conn))
            except Exception as e:  # 1ソース全滅でも他ソースは続行
                logger.exception("scrape source failed entirely: %s", source)
                all_stats.append(
                    ScrapeStats(source=source, queries_total=1, queries_failed=1, errors=[str(e)])
                )

        # メルカリ: 今回見えなかった出品は売切れ扱い。ただし全クエリ失敗時はスキップし、
        # 部分失敗ではそのカードだけ除外する(取得失敗＝売切れではない。
        # ネットワーク断・bot検知で販売中の在庫を誤って消さないため)
        mercari_stats = next((s for s in all_stats if s.source == "mercari"), None)
        if mercari_stats and mercari_stats.queries_total > 0 and (
            mercari_stats.queries_failed < mercari_stats.queries_total
        ):
            stale = db.deactivate_stale_mercari(
                conn, started_at, exclude_card_ids=mercari_stats.failed_card_ids
            )
            logger.info("mercari stale listings deactivated: %d", stale)
            conn.commit()

        deals = recompute_matches(cfg, conn, fx_rate=fx_rate)

        from . import notify  # Discord未設定でも他が動くよう遅延import

        notify.send_notifications(cfg, conn, deals, all_stats)
        notify.send_daily_digest(cfg, conn)

        # サイト用JSONを書き出す(この後 scripts/daily.sh が git push する)
        if bool(cfg.get("export.enabled", True)):
            from .export import export_site_data

            export_site_data(cfg, conn)

        total_failures = sum(s.queries_failed + s.parse_failures for s in all_stats)
        print(
            f"done: deals={len(deals)} "
            f"scraped={sum(s.items_found for s in all_stats)} failures={total_failures}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    run_daily()
