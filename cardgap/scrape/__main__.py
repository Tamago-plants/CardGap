"""スクレイパー単体のCLI。動作確認用。

例:
  python -m cardgap.scrape ebay --query "charizard 201/190"
  python -m cardgap.scrape mercari --query "リザードン 201/190" --store
  python -m cardgap.scrape snkrdunk --from-html tests/fixtures/snkrdunk_search_sample.html
  python -m cardgap.scrape ebay --watchlist --limit 3   # watchlist先頭3件で本番同様に実行
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from importlib import import_module
from pathlib import Path

from .. import db
from ..config import load_config

SOURCES = ("ebay", "mercari", "snkrdunk")


def _print_result(parsed) -> None:
    for item in parsed.items:
        print(json.dumps(asdict(item), ensure_ascii=False))
    print(
        f"# items={len(parsed.items)} parse_failures={parsed.parse_failures}",
        file=sys.stderr,
    )
    for err in parsed.errors:
        print(f"# error: {err}", file=sys.stderr)


def _store(source: str, conn, parsed) -> int:
    if source == "ebay":
        return db.insert_ebay_sold(conn, parsed.items)
    if source == "mercari":
        return db.upsert_mercari(conn, parsed.items)
    return db.upsert_snkrdunk(conn, parsed.items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cardgap.scrape")
    parser.add_argument("source", choices=SOURCES)
    parser.add_argument("--query", help="検索クエリを直接指定して1回だけ実行")
    parser.add_argument("--from-html", help="保存済みHTMLをパースする(ネットワーク不要)")
    parser.add_argument("--watchlist", action="store_true", help="watchlist全件で本番同様に実行(DB保存あり)")
    parser.add_argument("--store", action="store_true", help="--query の結果もDBに保存する")
    parser.add_argument("--limit", type=int, help="--watchlist 時のクエリ数上限")
    parser.add_argument("--config", help="config.yaml のパス")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    mod = import_module(f"cardgap.scrape.{args.source}")

    if args.from_html:
        html = Path(args.from_html).read_text(encoding="utf-8")
        parsed = mod.parse_search_html(html, raw_query=args.query or "")
        _print_result(parsed)
        return 0

    if args.query:
        parsed = mod.fetch_query(args.query, cfg)
        _print_result(parsed)
        if args.store:
            conn = db.connect(cfg.db_path())
            n = _store(args.source, conn, parsed)
            conn.commit()
            conn.close()
            print(f"# stored {n} items", file=sys.stderr)
        return 0

    if args.watchlist:
        from ..pipeline import run_scrape
        from ..watchlist import import_watchlist

        conn = db.connect(cfg.db_path())
        import_watchlist(conn, cfg)
        stats = run_scrape(args.source, cfg, conn, limit_queries=args.limit)
        conn.close()
        print(
            f"# queries={stats.queries_total} failed={stats.queries_failed} "
            f"items={stats.items_found} parse_failures={stats.parse_failures}",
            file=sys.stderr,
        )
        return 0

    parser.error("--query / --from-html / --watchlist のいずれかを指定してください")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
