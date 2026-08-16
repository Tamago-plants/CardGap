"""Discord 日次ダイジェスト(cardgap.notify の digest 系)のテスト。

build_digest_messages は summary の dict をテスト内で直接組み立てて検証する
(スキーマは export.build_summary_payload() = summary.json と同じ)。
send_daily_digest は requests.post を monkeypatch し、DB はインメモリを使う。
ネットワークには一切出ない。
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from cardgap import db, notify
from cardgap.config import Config

WEBHOOK = "https://discord.example.test/api/webhooks/123/abc"


# -------------------------------------------------------------------- fixtures

@pytest.fixture(autouse=True)
def _clear_webhook_env(monkeypatch):
    """環境変数 DISCORD_WEBHOOK_URL がテスト結果を汚さないよう常に消す。"""
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)


@pytest.fixture()
def conn():
    """インメモリDB(connect がスキーマも作る)。空でも summary は組める。"""
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


def _cfg(webhook: str = WEBHOOK, daily_digest: bool = True) -> Config:
    """config.yaml と同じ構造の dict から直接構築(ファイル非依存)。"""
    return Config(
        {
            "discord": {"webhook_url": webhook, "daily_digest": daily_digest},
            "threshold": {"min_profit_jpy": 5000, "min_profit_rate": 0.20},
            "export": {"top_n": 10, "movers_n": 5},
        }
    )


# ------------------------------------------------------ summary dict builders

def _top_entry(
    display_name: str = "リザードン 201/190 s12a PSA10",
    source: str = "mercari",
    buy_price_jpy: int = 5000,
    profit_jpy: float = 10000.0,
    profit_rate: float = 0.42,
    listing_url: str = "https://jp.mercari.com/item/m1",
) -> dict[str, Any]:
    """summary.top_by_rate の1件(ダイジェストが読むキーのみ)。"""
    return {
        "display_name": display_name,
        "source": source,
        "buy_price_jpy": buy_price_jpy,
        "profit_jpy": profit_jpy,
        "profit_rate": profit_rate,
        "listing_url": listing_url,
    }


def _health_entry(
    source: str = "ebay",
    queries_total: int = 50,
    queries_failed: int = 2,
    items_found: int = 830,
    parse_failures: int = 3,
) -> dict[str, Any]:
    """summary.scrape_health の1件。"""
    return {
        "source": source,
        "started_at": "2026-08-16T00:00:00Z",
        "finished_at": "2026-08-16T00:10:00Z",
        "queries_total": queries_total,
        "queries_failed": queries_failed,
        "items_found": items_found,
        "parse_failures": parse_failures,
    }


def _summary(
    date: str = "2026-08-16",
    fx_rate: Optional[float] = 150.5,
    deal_count_total: int = 12,
    deal_count_above_threshold: int = 3,
    top_by_rate: Optional[list[dict[str, Any]]] = None,
    movers_up: Optional[list[dict[str, Any]]] = None,
    movers_down: Optional[list[dict[str, Any]]] = None,
    scrape_health: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """export.build_summary_payload() と同じスキーマの summary を直接組み立てる。"""
    return {
        "generated_at": f"{date}T01:23:45Z",
        "date": date,
        "fx_rate": fx_rate,
        "thresholds": {
            "min_profit_jpy": 5000,
            "min_profit_rate": 0.20,
            "min_sold_count_30d": 3,
        },
        "deal_count_total": deal_count_total,
        "deal_count_above_threshold": deal_count_above_threshold,
        "top_by_rate": top_by_rate or [],
        "top_by_profit": top_by_rate or [],
        "movers_up": movers_up or [],
        "movers_down": movers_down or [],
        "scrape_health": scrape_health or [],
    }


def _embed_by_title(messages: list[dict[str, Any]], title: str) -> dict[str, Any]:
    for msg in messages:
        for e in msg.get("embeds", []):
            if e["title"] == title:
                return e
    raise AssertionError(f"embed '{title}' が見つからない")


# ------------------------------------------------------- build_digest_messages

def test_build_digest_is_single_message_with_three_embeds():
    messages = notify.build_digest_messages(_summary())
    assert len(messages) == 1
    embeds = messages[0]["embeds"]
    assert len(embeds) <= 10  # Discord の上限
    assert [e["title"] for e in embeds] == ["サマリ", "利益率ランキング TOP5", "相場動向"]


def test_build_digest_content_has_date():
    messages = notify.build_digest_messages(_summary(date="2026-08-16"))
    assert messages[0]["content"] == "📊 CardGap 日次ダイジェスト (2026-08-16)"


def test_summary_embed_counts_and_fx():
    messages = notify.build_digest_messages(
        _summary(deal_count_total=12, deal_count_above_threshold=3, fx_rate=150.5)
    )
    fields = {f["name"]: f["value"] for f in _embed_by_title(messages, "サマリ")["fields"]}
    assert fields["閾値超え案件"] == "3 / 12件"
    assert fields["USD/JPY"] == "¥150.50"


def test_summary_embed_fx_missing():
    messages = notify.build_digest_messages(_summary(fx_rate=None))
    fields = {f["name"]: f["value"] for f in _embed_by_title(messages, "サマリ")["fields"]}
    assert fields["USD/JPY"] == "取得なし"


def test_health_lines_format_and_warn_mark():
    health = [
        _health_entry("ebay", queries_total=50, queries_failed=2, items_found=830, parse_failures=3),
        # クエリ失敗が半分超(6/10)→ ⚠
        _health_entry("mercari", queries_total=10, queries_failed=6, items_found=40, parse_failures=0),
        # パース失敗が半分超(9/10)→ ⚠
        _health_entry("snkrdunk", queries_total=10, queries_failed=0, items_found=40, parse_failures=9),
    ]
    messages = notify.build_digest_messages(_summary(scrape_health=health))
    fields = {f["name"]: f["value"] for f in _embed_by_title(messages, "サマリ")["fields"]}
    lines = fields["収集ヘルス"].split("\n")
    assert lines == [
        "ebay: 50クエリ 失敗2 取得830件 パース失敗3",
        "⚠ mercari: 10クエリ 失敗6 取得40件 パース失敗0",
        "⚠ snkrdunk: 10クエリ 失敗0 取得40件 パース失敗9",
    ]


def test_health_half_exactly_is_not_warned():
    # ちょうど半分(25/50)は「>半分」ではないので ⚠ なし
    health = [_health_entry("ebay", queries_total=50, queries_failed=25, parse_failures=25)]
    messages = notify.build_digest_messages(_summary(scrape_health=health))
    fields = {f["name"]: f["value"] for f in _embed_by_title(messages, "サマリ")["fields"]}
    assert not fields["収集ヘルス"].startswith("⚠")


def test_ranking_line_format():
    top = [
        _top_entry(
            display_name="リザードン 201/190 s12a PSA10",
            source="mercari",
            buy_price_jpy=12500,
            profit_jpy=8765.4,
            profit_rate=0.42,
            listing_url="https://jp.mercari.com/item/m1",
        )
    ]
    messages = notify.build_digest_messages(_summary(top_by_rate=top))
    desc = _embed_by_title(messages, "利益率ランキング TOP5")["description"]
    assert desc == (
        "1. リザードン 201/190 s12a PSA10 [mercari] 仕入¥12,500 "
        "→ 利益¥8,765 (42%) https://jp.mercari.com/item/m1"
    )


def test_ranking_takes_only_top5_numbered():
    top = [
        _top_entry(listing_url=f"https://jp.mercari.com/item/m{i}", profit_rate=0.9 - i * 0.1)
        for i in range(7)
    ]
    messages = notify.build_digest_messages(_summary(top_by_rate=top))
    lines = _embed_by_title(messages, "利益率ランキング TOP5")["description"].split("\n")
    assert len(lines) == 5
    assert [ln.split(".")[0] for ln in lines] == ["1", "2", "3", "4", "5"]
    assert lines[4].endswith("https://jp.mercari.com/item/m4")


def test_ranking_empty_fallback():
    messages = notify.build_digest_messages(_summary(top_by_rate=[]))
    desc = _embed_by_title(messages, "利益率ランキング TOP5")["description"]
    assert desc == "本日の閾値超え案件はありません"


def test_movers_lines_up_and_down():
    up = [
        {
            "display_name": "ピカチュウ 001/100 PSA10",
            "prev_median_usd": 10.0,
            "median_usd": 12.0,
            "change_rate": 0.2,
            "count": 5,
        }
    ]
    down = [
        {
            "display_name": "ミュウ 002/100",
            "prev_median_usd": 20.0,
            "median_usd": 17.0,
            "change_rate": -0.15,
            "count": 4,
        }
    ]
    messages = notify.build_digest_messages(_summary(movers_up=up, movers_down=down))
    lines = _embed_by_title(messages, "相場動向")["description"].split("\n")
    assert lines == [
        "📈 ピカチュウ 001/100 PSA10 $ 10.0 → $ 12.0 (+20.0%, 5件)",
        "📉 ミュウ 002/100 $ 20.0 → $ 17.0 (-15.0%, 4件)",
    ]


def test_movers_empty_fallback():
    messages = notify.build_digest_messages(_summary(movers_up=[], movers_down=[]))
    desc = _embed_by_title(messages, "相場動向")["description"]
    assert desc == "変動データなし(履歴が2日分たまると表示されます)"


# ----------------------------------------------------------- send_daily_digest

def test_send_skips_when_daily_digest_disabled(conn, monkeypatch):
    rec = _PostRecorder()
    _patch_post(monkeypatch, rec)

    assert notify.send_daily_digest(_cfg(daily_digest=False), conn) is True
    assert rec.calls == []


def test_send_without_webhook_returns_true_when_not_forced(conn, monkeypatch):
    rec = _PostRecorder()
    _patch_post(monkeypatch, rec)

    assert notify.send_daily_digest(_cfg(webhook=""), conn) is True
    assert rec.calls == []


def test_send_without_webhook_returns_false_when_forced(conn, monkeypatch):
    rec = _PostRecorder()
    _patch_post(monkeypatch, rec)

    assert notify.send_daily_digest(_cfg(webhook=""), conn, force=True) is False
    assert rec.calls == []


def test_send_success_posts_payload_with_embeds(conn, monkeypatch):
    rec = _PostRecorder(status_code=204)
    _patch_post(monkeypatch, rec)

    assert notify.send_daily_digest(_cfg(), conn) is True
    assert len(rec.calls) == 1
    call = rec.calls[0]
    assert call["url"] == WEBHOOK
    assert call["timeout"] == 15
    payload = call["json"]
    assert payload["content"].startswith("📊 CardGap 日次ダイジェスト (")
    titles = [e["title"] for e in payload["embeds"]]
    assert titles == ["サマリ", "利益率ランキング TOP5", "相場動向"]
    # 空DBなのでランキング・騰落はフォールバック文言になる
    assert payload["embeds"][1]["description"] == "本日の閾値超え案件はありません"
    assert payload["embeds"][2]["description"] == "変動データなし(履歴が2日分たまると表示されます)"


def test_send_force_overrides_disabled_config(conn, monkeypatch):
    rec = _PostRecorder(status_code=200)
    _patch_post(monkeypatch, rec)

    assert notify.send_daily_digest(_cfg(daily_digest=False), conn, force=True) is True
    assert len(rec.calls) == 1


def test_send_500_returns_false(conn, monkeypatch):
    rec = _PostRecorder(status_code=500)
    _patch_post(monkeypatch, rec)

    assert notify.send_daily_digest(_cfg(), conn) is False
    assert len(rec.calls) == 1


def test_send_exception_returns_false(conn, monkeypatch):
    rec = _PostRecorder(raise_exc=ConnectionError("接続失敗"))
    _patch_post(monkeypatch, rec)

    assert notify.send_daily_digest(_cfg(), conn) is False
