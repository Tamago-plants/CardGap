"""eBay相場の鮮度警告(notify._ebay_staleness_line)のテスト。

クラウドがeBayを試行しない運用では、PC実行をサボるとeBay相場が
静かに古くなるため、ダイジェストのサマリで警告する。
"""

from __future__ import annotations

from cardgap import notify


def _summary(ebay_started: str | None, date: str = "2026-09-26") -> dict:
    health = [
        {"source": "mercari", "started_at": f"{date}T07:00:00Z",
         "finished_at": None, "queries_total": 39, "queries_failed": 0,
         "items_found": 1800, "parse_failures": 0},
    ]
    if ebay_started is not None:
        health.append(
            {"source": "ebay", "started_at": ebay_started, "finished_at": None,
             "queries_total": 40, "queries_failed": 0, "items_found": 500,
             "parse_failures": 0}
        )
    return {
        "date": date,
        "deal_count_total": 10,
        "deal_count_above_threshold": 1,
        "fx_rate": 150.0,
        "scrape_health": health,
    }


def test_stale_warns_after_threshold_days():
    line = notify._ebay_staleness_line(_summary("2026-09-20T21:00:00Z"))
    assert line is not None and "6日更新されていません" in line
    # サマリembedの収集ヘルスにも載る
    embed = notify._digest_summary_embed(_summary("2026-09-20T21:00:00Z"))
    health_field = next(f for f in embed["fields"] if f["name"] == "収集ヘルス")
    assert "⚠ eBay相場が6日更新されていません" in health_field["value"]


def test_fresh_run_no_warning():
    assert notify._ebay_staleness_line(_summary("2026-09-24T21:00:00Z")) is None  # 2日前


def test_no_ebay_row_no_warning():
    assert notify._ebay_staleness_line(_summary(None)) is None


def test_bad_date_no_warning():
    assert notify._ebay_staleness_line(_summary("unknown")) is None
    assert notify._ebay_staleness_line({"scrape_health": [{"source": "ebay"}]}) is None
