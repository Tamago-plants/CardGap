"""サイト用の静的JSONエクスポート。

日次バッチの最後に site/public/data/ 配下へ以下を書き出す。
自宅PC側がこれを git push すると GitHub Actions がサイトを再ビルドして
GitHub Pages が更新される、という流れの「データ受け渡し点」。

  deals.json   : 現在の全案件(無視リスト除外済み)。サイトのメインテーブル用
  history.json : カード別の日次相場スナップショット。価格推移チャート用
  summary.json : 日次サマリ(ランキング・騰落・収集ヘルス)。サイトのトップと
                 Discord日次ダイジェストの共通データソース

JSONのキーは site/ 側(React)と cardgap/notify.py のダイジェストが読む契約。
変更するときは両方を同時に直すこと。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from . import db
from .config import Config

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _card_label(row: dict[str, Any]) -> str:
    """JSON内で使うカードの表示名(日本語名 + 番号 + セット + PSA)。"""
    parts = [row.get("name_ja") or row.get("card_name") or ""]
    if row.get("card_number"):
        parts.append(str(row["card_number"]))
    if row.get("set_code"):
        parts.append(str(row["set_code"]))
    if row.get("psa_grade"):
        parts.append(f"PSA{int(row['psa_grade'])}")
    return " ".join(p for p in parts if p)


def _deal_to_json(r: dict[str, Any]) -> dict[str, Any]:
    """db.list_deals() の1行をサイト用のフラットな dict に変換。"""
    return {
        "card_id": r["card_id"],
        "category": r["category"],
        "name_ja": r["card_name"],
        "name_en": r["name_en"],
        "set_code": r["set_code"],
        "card_number": r["card_number"],
        "psa_grade": r["psa_grade"],
        "display_name": _card_label({**r, "name_ja": r["card_name"]}),
        "source": r["source"],
        "title": r["title"],
        "buy_price_jpy": r["buy_price_jpy"],
        "listing_url": r["listing_url"],
        "image_url": r["image_url"],
        "confidence": r["confidence"],
        "reliability": r["reliability"],
        "ebay_median_usd": r["ebay_median_usd"],
        "ebay_count_30d": r["ebay_count_30d"],
        "ebay_min_usd": r["ebay_min_usd"],
        "ebay_max_usd": r["ebay_max_usd"],
        "buy_total_jpy": r["buy_total_jpy"],
        "revenue_jpy": r["revenue_jpy"],
        "ebay_fees_jpy": r["ebay_fees_jpy"],
        "profit_jpy": r["profit_jpy"],
        "profit_rate": r["profit_rate"],
        "fx_rate": r["fx_rate"],
        "computed_at": r["computed_at"],
        "first_seen_at": r["first_seen_at"],  # サイトの NEW バッジ用(初観測日時)
    }


def build_deals_payload(cfg: Config, conn: sqlite3.Connection) -> dict[str, Any]:
    rows = db.list_deals(conn)  # 無視リスト除外済み・利益率降順
    return {
        "generated_at": _now_iso(),
        "deals": [_deal_to_json(r) for r in rows],
    }


def build_history_payload(
    cfg: Config, conn: sqlite3.Connection, days: Optional[int] = None
) -> dict[str, Any]:
    days = days or int(cfg.get("export.history_days", 90))
    since = (date.today() - timedelta(days=days)).isoformat()
    cards_out: list[dict[str, Any]] = []
    for card in db.list_cards(conn, enabled_only=False):
        rows = db.market_history_for_card(conn, card.id, since_date=since)
        if not rows:
            continue
        cards_out.append(
            {
                "card_id": card.id,
                "category": card.category,
                "name_ja": card.name_ja,
                "name_en": card.name_en,
                "set_code": card.set_code,
                "card_number": card.card_number,
                "psa_grade": card.psa_grade,
                "display_name": card.display_name(),
                "points": [
                    {
                        "date": r["date"],
                        "median_usd": r["median_usd"],
                        "count": r["count"],
                        "min_usd": r["min_usd"],
                        "max_usd": r["max_usd"],
                    }
                    for r in rows
                ],
            }
        )
    return {"generated_at": _now_iso(), "days": days, "cards": cards_out}


def _compute_movers(
    conn: sqlite3.Connection, max_gap_days: int = 8
) -> list[dict[str, Any]]:
    """全カードの「最新スナップショット vs その前回」の中央値騰落率を返す。

    前回が max_gap_days より古い場合は比較しない(休止明けの見かけ上の急変を防ぐ)。
    """
    movers: list[dict[str, Any]] = []
    for card in db.list_cards(conn, enabled_only=False):
        snaps = db.latest_two_snapshots(conn, card.id)
        if len(snaps) < 2:
            continue
        latest, prev = snaps[0], snaps[1]
        try:
            gap = (date.fromisoformat(latest["date"]) - date.fromisoformat(prev["date"])).days
        except ValueError:
            continue
        if gap > max_gap_days or prev["median_usd"] <= 0:
            continue
        change = (latest["median_usd"] - prev["median_usd"]) / prev["median_usd"]
        movers.append(
            {
                "card_id": card.id,
                "display_name": card.display_name(),
                "category": card.category,
                "median_usd": latest["median_usd"],
                "prev_median_usd": prev["median_usd"],
                "change_rate": round(change, 4),
                "count": latest["count"],
                "date": latest["date"],
                "prev_date": prev["date"],
            }
        )
    return movers


def build_summary_payload(cfg: Config, conn: sqlite3.Connection) -> dict[str, Any]:
    top_n = int(cfg.get("export.top_n", 10))
    movers_n = int(cfg.get("export.movers_n", 5))
    min_rate = float(cfg.get("threshold.min_profit_rate", 0.2))
    min_profit = float(cfg.get("threshold.min_profit_jpy", 5000))

    all_rows = [_deal_to_json(r) for r in db.list_deals(conn)]
    above = [
        r
        for r in all_rows
        if r["profit_rate"] >= min_rate
        and r["profit_jpy"] >= min_profit
        and r["reliability"] == "ok"
        and r["confidence"] in ("high", "medium")
    ]
    movers = _compute_movers(conn)
    movers_up = sorted(
        [m for m in movers if m["change_rate"] > 0],
        key=lambda m: m["change_rate"],
        reverse=True,
    )[:movers_n]
    movers_down = sorted(
        [m for m in movers if m["change_rate"] < 0], key=lambda m: m["change_rate"]
    )[:movers_n]

    return {
        "generated_at": _now_iso(),
        "date": date.today().isoformat(),
        "site_url": cfg.get("export.site_url", "") or None,  # Discordダイジェストのリンク用
        "fx_rate": db.latest_fx_rate(conn),
        "thresholds": {
            "min_profit_jpy": min_profit,
            "min_profit_rate": min_rate,
            "min_sold_count_30d": int(cfg.get("threshold.min_sold_count_30d", 3)),
        },
        # サイト側の What-if 損益シミュレータ用。Python 側 profit.py と同じ式を
        # クライアントで再現するためのパラメータ一式
        "profit_model": {
            "conversion_margin": float(cfg.get("fx.conversion_margin", 0.02)),
            "final_value_fee": float(cfg.get("ebay_fees.final_value_fee", 0.1325)),
            "per_order_fee_usd": float(cfg.get("ebay_fees.per_order_fee_usd", 0.30)),
            "international_fee": float(cfg.get("ebay_fees.international_fee", 0.0135)),
            "promoted_listing": float(cfg.get("ebay_fees.promoted_listing", 0.02)),
            "ship_out_jpy": float(cfg.get("shipping.default_out_jpy", 2500)),
            "buy": {
                "mercari": {
                    "fee_rate": float(cfg.get("buy_side.mercari_fee_rate", 0.0)),
                    "shipping_jpy": float(cfg.get("buy_side.mercari_shipping_jpy", 0)),
                },
                "snkrdunk": {
                    "fee_rate": float(cfg.get("buy_side.snkrdunk_buyer_fee_rate", 0.055)),
                    "shipping_jpy": float(cfg.get("buy_side.snkrdunk_shipping_jpy", 1000)),
                },
            },
        },
        "deal_count_total": len(all_rows),
        "deal_count_above_threshold": len(above),
        "top_by_rate": sorted(above, key=lambda r: r["profit_rate"], reverse=True)[:top_n],
        "top_by_profit": sorted(above, key=lambda r: r["profit_jpy"], reverse=True)[:top_n],
        "movers_up": movers_up,
        "movers_down": movers_down,
        "scrape_health": [
            {
                "source": r["source"],
                "started_at": r["started_at"],
                "finished_at": r["finished_at"],
                "queries_total": r["queries_total"],
                "queries_failed": r["queries_failed"],
                "items_found": r["items_found"],
                "parse_failures": r["parse_failures"],
            }
            for r in db.latest_scrape_runs(conn)
        ],
    }


def export_site_data(
    cfg: Config, conn: sqlite3.Connection, out_dir: str | Path | None = None
) -> list[Path]:
    """3つのJSONを out_dir(既定: config の export.output_dir)へ書き出す。"""
    out = Path(out_dir) if out_dir else cfg.resolve_path(
        cfg.get("export.output_dir", "site/public/data")
    )
    out.mkdir(parents=True, exist_ok=True)
    payloads = {
        "deals.json": build_deals_payload(cfg, conn),
        "history.json": build_history_payload(cfg, conn),
        "summary.json": build_summary_payload(cfg, conn),
    }
    written: list[Path] = []
    for name, payload in payloads.items():
        path = out / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        written.append(path)
        logger.info("exported %s (%d bytes)", path, path.stat().st_size)
    return written
