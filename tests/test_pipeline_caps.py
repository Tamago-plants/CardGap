"""pipeline.run_scrape の eBay 日次クエリ上限とローテーションのテスト。

browser 層(new_page / fetch_html)とパーサをスタブし、ネットワーク・Playwright
なしで本物の run_scrape / scrape_runs 集計を検証する。
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

import cardgap.pipeline as pipeline
import cardgap.scrape.ebay as ebay_mod
from cardgap import db
from cardgap.config import Config
from cardgap.models import Card
from cardgap.scrape import ParsedPage


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def _cfg(cap: int = 50) -> Config:
    return Config(
        {
            "categories": {"pokemon": {"enabled": True}},
            "scrape": {"max_ebay_queries_per_day": cap},
        }
    )


@pytest.fixture
def stubbed(monkeypatch):
    """browser とパーサをスタブし、build_query されたカード英名を記録する。"""
    queried: list[str] = []

    @contextmanager
    def fake_page(cfg):
        yield None

    monkeypatch.setattr(pipeline.browser, "new_page", fake_page)
    monkeypatch.setattr(pipeline.browser, "fetch_html", lambda *a, **k: "<html></html>")
    monkeypatch.setattr(ebay_mod, "parse_search_html", lambda html, raw_query="": ParsedPage())

    real_build = ebay_mod.build_query

    def spy_build(card):
        queried.append(card.name_en)
        return real_build(card)

    monkeypatch.setattr(ebay_mod, "build_query", spy_build)
    return queried


def _make_cards(conn, n: int) -> list[Card]:
    cards = []
    for i in range(n):
        c = Card(
            category="pokemon",
            name_ja=f"ポケ{i:02d}",
            name_en=f"Poke{i:02d}",  # ゼロ埋めで name_en 順 = 登録順にする
            set_code="s1",
            card_number=f"{i + 1}/100",
            psa_grade=None,
        )
        c.id = db.upsert_card(conn, c)
        cards.append(c)
    conn.commit()
    return cards


def test_ebay_daily_cap_across_runs_and_rotation(conn, stubbed):
    _make_cards(conn, 60)

    # 1回目: 上限50件まで(watchlist 60枚の先頭から)
    s1 = pipeline.run_scrape("ebay", _cfg(cap=50), conn)
    assert s1.queries_total == 50
    assert stubbed == [f"Poke{i:02d}" for i in range(50)]

    # 同日2回目: 日次上限を消費済みなので 1 クエリも投げない
    stubbed.clear()
    s2 = pipeline.run_scrape("ebay", _cfg(cap=50), conn)
    assert s2.queries_total == 0
    assert stubbed == []

    # 翌日(実行ログを前日に付け替えてシミュレート): 未消化の後方カードから巡回する
    conn.execute("UPDATE scrape_runs SET started_at = '2000-01-01T00:00:00Z'")
    conn.commit()
    stubbed.clear()
    s3 = pipeline.run_scrape("ebay", _cfg(cap=50), conn)
    assert s3.queries_total == 50
    assert stubbed[:10] == [f"Poke{i:02d}" for i in range(50, 60)]  # 前日の続き
    assert stubbed[10:] == [f"Poke{i:02d}" for i in range(40)]  # 折り返し


def test_ebay_limit_queries_respects_daily_budget(conn, stubbed):
    _make_cards(conn, 10)
    s1 = pipeline.run_scrape("ebay", _cfg(cap=5), conn, limit_queries=3)
    assert s1.queries_total == 3
    s2 = pipeline.run_scrape("ebay", _cfg(cap=5), conn, limit_queries=10)
    assert s2.queries_total == 2  # 残量 5-3=2 でクリップされる


def test_non_ebay_source_has_no_daily_cap(conn, stubbed, monkeypatch):
    import cardgap.scrape.mercari as mercari_mod

    monkeypatch.setattr(
        mercari_mod, "parse_search_html", lambda html, raw_query="": ParsedPage()
    )
    _make_cards(conn, 60)
    s = pipeline.run_scrape("mercari", _cfg(cap=5), conn)
    assert s.queries_total == 60  # メルカリは eBay の日次上限の対象外
