"""Discord 通知(cardgap.notify)のテスト。

requests.post を monkeypatch してペイロードを収集する。ネットワークには一切出ない。
DB は sqlite3 の ":memory:" を使う。
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from cardgap import db, notify
from cardgap.config import Config
from cardgap.models import (
    CONF_HIGH,
    CONF_LOW,
    CONF_MEDIUM,
    RELIABILITY_LOW,
    RELIABILITY_OK,
    Card,
    Deal,
    MarketStats,
    ProfitResult,
    ScrapeStats,
)

WEBHOOK = "https://discord.example.test/api/webhooks/123/abc"


# -------------------------------------------------------------------- fixtures

@pytest.fixture(autouse=True)
def _clear_webhook_env(monkeypatch):
    """環境変数 DISCORD_WEBHOOK_URL がテスト結果を汚さないよう常に消す。"""
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)


@pytest.fixture()
def conn():
    """インメモリDB(connect がスキーマも作る)。"""
    c = db.connect(":memory:")
    yield c
    c.close()


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _PostRecorder:
    """requests.post の代役。呼び出しを記録して固定ステータスを返す。"""

    def __init__(self, status_code: int = 204, raise_exc: Optional[Exception] = None):
        self.status_code = status_code
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, json: Any = None, timeout: Any = None) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self.raise_exc is not None:
            raise self.raise_exc
        return _FakeResponse(self.status_code)


def _patch_post(monkeypatch, recorder: _PostRecorder) -> None:
    monkeypatch.setattr("cardgap.notify.requests.post", recorder)


def _cfg(webhook: str = WEBHOOK, max_per_msg: int = 10) -> Config:
    """config.yaml と同じ構造の dict から直接構築(ファイル非依存)。"""
    return Config(
        {
            "threshold": {"min_profit_jpy": 5000, "min_profit_rate": 0.20},
            "discord": {"webhook_url": webhook, "max_deals_per_message": max_per_msg},
        }
    )


def _deal(
    url: str = "https://jp.mercari.com/item/m1",
    profit_jpy: float = 10000.0,
    profit_rate: float = 0.5,
    reliability: str = RELIABILITY_OK,
    confidence: str = CONF_HIGH,
    image_url: Optional[str] = None,
    source: str = "mercari",
) -> Deal:
    card = Card(
        category="pokemon",
        name_ja="リザードン",
        name_en="Charizard",
        set_code="s12a",
        card_number="201/190",
        psa_grade=10,
        id=1,
    )
    stats = MarketStats(
        median_usd=100.0, count=5, min_usd=80.0, max_usd=120.0, reliability=reliability
    )
    profit = ProfitResult(
        revenue_jpy=14700.0,
        ebay_fees_jpy=2484.0,
        ship_out_jpy=2500.0,
        buy_total_jpy=5000.0,
        profit_jpy=profit_jpy,
        profit_rate=profit_rate,
        fx_rate=150.0,
    )
    return Deal(
        card=card,
        source=source,
        source_listing_id=1,
        title="リザードン 201/190 PSA10",
        buy_price_jpy=5000,
        listing_url=url,
        image_url=image_url,
        confidence=confidence,
        stats=stats,
        profit=profit,
    )


# ---------------------------------------------- filter_deals_for_notification

def test_filter_passes_only_qualified(conn):
    url_ignored = "https://jp.mercari.com/item/m_ignored"
    url_notified = "https://jp.mercari.com/item/m_notified"
    db.add_ignore(conn, "mercari", url_ignored)
    db.mark_notified(conn, "mercari", url_notified)

    good = _deal(url="https://jp.mercari.com/item/m_good")
    deals = [
        good,
        _deal(url="https://x/low_profit", profit_jpy=4999.0),          # 利益額が閾値未満
        _deal(url="https://x/low_rate", profit_rate=0.19),             # 利益率が閾値未満
        _deal(url="https://x/low_rel", reliability=RELIABILITY_LOW),   # 相場信頼度 low
        _deal(url="https://x/low_conf", confidence=CONF_LOW),          # confidence low
        _deal(url=url_ignored),                                        # 無視済み
        _deal(url=url_notified),                                       # 通知済み
    ]
    result = notify.filter_deals_for_notification(_cfg(), conn, deals)
    assert result == [good]


def test_filter_allows_medium_confidence_and_exact_thresholds(conn):
    # 閾値ちょうど・confidence=medium は通過する
    d = _deal(url="https://x/edge", profit_jpy=5000.0, profit_rate=0.20, confidence=CONF_MEDIUM)
    assert notify.filter_deals_for_notification(_cfg(), conn, [d]) == [d]


# ------------------------------------------------------------ build_deal_embed

def test_build_deal_embed_contents():
    d = _deal(image_url="https://img.example/a.jpg", profit_jpy=12345.0, profit_rate=0.42)
    e = notify.build_deal_embed(d)
    assert e["title"] == "リザードン 201/190 s12a PSA10 [メルカリ]"
    assert e["url"] == d.listing_url
    assert e["thumbnail"] == {"url": "https://img.example/a.jpg"}
    fields = {f["name"]: f["value"] for f in e["fields"]}
    assert fields["仕入価格"] == "¥5,000"
    assert fields["eBay相場中央値"] == "$100.00 (5件)"
    assert fields["実質利益"] == "¥12,345"
    assert fields["利益率"] == "42.0%"
    assert fields["confidence"] == CONF_HIGH


def test_build_deal_embed_no_thumbnail_without_image():
    e = notify.build_deal_embed(_deal(image_url=None))
    assert "thumbnail" not in e


def test_build_deal_embed_color_tiers():
    assert notify.build_deal_embed(_deal(profit_rate=0.50))["color"] == notify._COLOR_RATE_50
    assert notify.build_deal_embed(_deal(profit_rate=0.35))["color"] == notify._COLOR_RATE_30
    assert notify.build_deal_embed(_deal(profit_rate=0.25))["color"] == notify._COLOR_DEFAULT


# ------------------------------------------------------- build_failure_summary

def test_build_failure_summary_with_failures():
    stats = [
        ScrapeStats(source="ebay", queries_total=50, queries_failed=2, parse_failures=3),
        ScrapeStats(source="mercari", queries_total=10, queries_failed=0, parse_failures=0),
    ]
    assert (
        notify.build_failure_summary(stats)
        == "⚠ スクレイプ失敗: ebay クエリ失敗2/50, パース失敗3件"
    )


def test_build_failure_summary_multiple_sources():
    stats = [
        ScrapeStats(source="ebay", queries_total=50, queries_failed=2),
        ScrapeStats(source="mercari", queries_total=10, parse_failures=1),
    ]
    assert (
        notify.build_failure_summary(stats)
        == "⚠ スクレイプ失敗: ebay クエリ失敗2/50 / mercari パース失敗1件"
    )


def test_build_failure_summary_all_zero_returns_none():
    stats = [
        ScrapeStats(source="ebay", queries_total=50),
        ScrapeStats(source="mercari", queries_total=10),
    ]
    assert notify.build_failure_summary(stats) is None


# ---------------------------------------------------------- send_notifications

def test_send_splits_12_deals_into_two_messages(conn, monkeypatch):
    rec = _PostRecorder(status_code=204)
    _patch_post(monkeypatch, rec)
    deals = [_deal(url=f"https://jp.mercari.com/item/m{i}") for i in range(12)]

    assert notify.send_notifications(_cfg(), conn, deals, []) is True
    assert len(rec.calls) == 2
    assert all(c["url"] == WEBHOOK and c["timeout"] == 15 for c in rec.calls)

    first, second = rec.calls[0]["json"], rec.calls[1]["json"]
    assert first["content"] == "CardGap: 本日の検出 12件"
    assert len(first["embeds"]) == 10
    assert "content" not in second  # content は1通目のみ
    assert len(second["embeds"]) == 2

    # 送った全案件が通知済みになる
    for d in deals:
        assert db.is_notified(conn, d.listing_url)


def test_send_content_includes_failure_summary(conn, monkeypatch):
    rec = _PostRecorder(status_code=200)
    _patch_post(monkeypatch, rec)
    stats = [ScrapeStats(source="ebay", queries_total=50, queries_failed=2, parse_failures=3)]

    assert notify.send_notifications(_cfg(), conn, [_deal()], stats) is True
    content = rec.calls[0]["json"]["content"]
    assert content == (
        "CardGap: 本日の検出 1件\n⚠ スクレイプ失敗: ebay クエリ失敗2/50, パース失敗3件"
    )


def test_send_500_returns_false_and_marks_nothing(conn, monkeypatch):
    rec = _PostRecorder(status_code=500)
    _patch_post(monkeypatch, rec)
    d = _deal()

    assert notify.send_notifications(_cfg(), conn, [d], []) is False
    assert len(rec.calls) == 1
    assert not db.is_notified(conn, d.listing_url)


def test_send_exception_returns_false_and_marks_nothing(conn, monkeypatch):
    rec = _PostRecorder(raise_exc=ConnectionError("接続失敗"))
    _patch_post(monkeypatch, rec)
    d = _deal()

    assert notify.send_notifications(_cfg(), conn, [d], []) is False
    assert not db.is_notified(conn, d.listing_url)


def test_send_without_webhook_returns_true_and_no_post(conn, monkeypatch):
    rec = _PostRecorder()
    _patch_post(monkeypatch, rec)

    assert notify.send_notifications(_cfg(webhook=""), conn, [_deal()], []) is True
    assert rec.calls == []


def test_send_zero_deals_with_failures_sends_content_only(conn, monkeypatch):
    rec = _PostRecorder(status_code=204)
    _patch_post(monkeypatch, rec)
    stats = [ScrapeStats(source="mercari", queries_total=10, queries_failed=1)]

    assert notify.send_notifications(_cfg(), conn, [], stats) is True
    assert len(rec.calls) == 1
    payload = rec.calls[0]["json"]
    assert payload["content"] == (
        "CardGap: 本日の検出 0件\n⚠ スクレイプ失敗: mercari クエリ失敗1/10"
    )
    assert "embeds" not in payload


def test_send_zero_deals_zero_failures_sends_nothing(conn, monkeypatch):
    rec = _PostRecorder()
    _patch_post(monkeypatch, rec)
    stats = [ScrapeStats(source="ebay", queries_total=50)]

    assert notify.send_notifications(_cfg(), conn, [], stats) is True
    assert rec.calls == []


# ----------------------------------------------------------- send_test_message

def test_send_test_message_posts_content(monkeypatch):
    rec = _PostRecorder(status_code=204)
    _patch_post(monkeypatch, rec)

    assert notify.send_test_message(_cfg()) is True
    assert rec.calls[0]["json"] == {"content": "CardGap 疎通テスト"}
    assert rec.calls[0]["timeout"] == 15


def test_send_test_message_without_webhook_returns_false(monkeypatch):
    rec = _PostRecorder()
    _patch_post(monkeypatch, rec)

    assert notify.send_test_message(_cfg(webhook="")) is False
    assert rec.calls == []
