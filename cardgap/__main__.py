"""CardGap メインCLI。

例:
  python -m cardgap initdb                 # DB初期化 + watchlist取込
  python -m cardgap fx                     # 為替レート更新
  python -m cardgap match                  # DB内データで相場集計・損益再計算
  python -m cardgap deals [--min-rate 0.2] # 上位案件を表示
  python -m cardgap notify --test          # Discord疎通テスト
  python -m cardgap run                    # 日次バッチ一式(= python -m cardgap.pipeline)
スクレイプ単体は `python -m cardgap.scrape --help` を参照。
"""

from __future__ import annotations

import argparse
import logging

from . import db, fx
from .config import load_config
from .watchlist import import_watchlist


def cmd_initdb(args) -> int:
    cfg = load_config(args.config)
    conn = db.connect(cfg.db_path())
    n = import_watchlist(conn, cfg)
    conn.close()
    print(f"DB initialized at {cfg.db_path()} (watchlist: {n} cards)")
    return 0


def cmd_fx(args) -> int:
    cfg = load_config(args.config)
    conn = db.connect(cfg.db_path())
    rate = fx.get_usd_jpy(cfg, conn, refresh=True)
    conn.close()
    print(f"USD/JPY = {rate:.2f}")
    return 0


def cmd_match(args) -> int:
    from .pipeline import recompute_matches

    cfg = load_config(args.config)
    conn = db.connect(cfg.db_path())
    deals = recompute_matches(cfg, conn)
    conn.close()
    print(f"matches rebuilt: {len(deals)} deals")
    return 0


def cmd_deals(args) -> int:
    cfg = load_config(args.config)
    conn = db.connect(cfg.db_path())
    rows = db.list_deals(
        conn,
        min_profit_rate=args.min_rate,
        min_profit_jpy=args.min_profit,
        psa_only=args.psa_only,
    )
    for r in rows[: args.limit]:
        print(
            f"{r['profit_rate']*100:6.1f}%  ¥{r['profit_jpy']:>8,.0f}  "
            f"[{r['source']}] {r['card_name']} {r['card_number'] or ''} "
            f"(conf={r['confidence']}, ebay {r['ebay_count_30d']}件 "
            f"${r['ebay_median_usd']}) {r['listing_url']}"
        )
    print(f"# total {len(rows)} deals")
    return 0


def cmd_notify(args) -> int:
    from . import notify

    cfg = load_config(args.config)
    if args.test:
        ok = notify.send_test_message(cfg)
        print("Discord OK" if ok else "Discord failed (webhook URL 設定を確認)")
        return 0 if ok else 1
    conn = db.connect(cfg.db_path())
    from .pipeline import recompute_matches

    deals = recompute_matches(cfg, conn)
    ok = notify.send_notifications(cfg, conn, deals, [])
    conn.close()
    return 0 if ok else 1


def cmd_run(args) -> int:
    from .pipeline import run_daily

    run_daily(load_config(args.config))
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m cardgap")
    parser.add_argument("--config", help="config.yaml のパス")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("initdb", help="DB初期化 + watchlist取込")
    sub.add_parser("fx", help="為替レート更新")
    sub.add_parser("match", help="相場集計・損益再計算(スクレイプなし)")

    p_deals = sub.add_parser("deals", help="上位案件を表示")
    p_deals.add_argument("--min-rate", type=float, default=None)
    p_deals.add_argument("--min-profit", type=float, default=None)
    p_deals.add_argument("--psa-only", action="store_true")
    p_deals.add_argument("--limit", type=int, default=30)

    p_notify = sub.add_parser("notify", help="Discord通知")
    p_notify.add_argument("--test", action="store_true", help="疎通テストのみ")

    sub.add_parser("run", help="日次バッチ一式")

    args = parser.parse_args()
    handlers = {
        "initdb": cmd_initdb,
        "fx": cmd_fx,
        "match": cmd_match,
        "deals": cmd_deals,
        "notify": cmd_notify,
        "run": cmd_run,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
