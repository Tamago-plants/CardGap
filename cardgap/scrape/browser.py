"""Playwright まわりの共通処理: 起動、レート制限、リトライ、HTMLダンプ。

個人利用・低頻度アクセスの前提を崩さないため、fetch_html() は必ず
polite_sleep()(2〜5秒のランダムディレイ)を挟んでから取得する。
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from ..config import Config

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# navigator.webdriver を隠す等の最低限のステルス
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['ja-JP', 'ja', 'en-US'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
window.chrome = window.chrome || { runtime: {} };
"""


def polite_sleep(cfg: Config) -> None:
    lo = float(cfg.get("scrape.delay_min_s", 2.0))
    hi = float(cfg.get("scrape.delay_max_s", 5.0))
    time.sleep(random.uniform(lo, max(lo, hi)))


@contextmanager
def new_page(cfg: Config) -> Iterator["Page"]:  # noqa: F821 (Playwright型は実行時import)
    """Playwright ページを1つ開く。スクレイプ1ソース分で1コンテキスト使い回す。"""
    from playwright.sync_api import sync_playwright

    headless = bool(cfg.get("scrape.headless", True))
    # Playwright同梱ブラウザ以外(システムのChrome等)を使う場合の逃げ道。
    # 環境変数 CARDGAP_CHROMIUM_PATH が config より優先される。
    executable = os.environ.get("CARDGAP_CHROMIUM_PATH") or cfg.get(
        "scrape.chromium_executable", ""
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            executable_path=executable or None,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        context.add_init_script(_STEALTH_JS)
        page = context.new_page()
        page.set_default_timeout(float(cfg.get("scrape.timeout_ms", 30000)))
        try:
            yield page
        finally:
            context.close()
            browser.close()


# bot検知チャレンジページの典型ワード(診断ログ用)
_CHALLENGE_MARKERS = (
    "captcha", "pardon our interruption", "verify yourself", "are you a human",
    "unusual traffic", "access denied", "robot", "checking your browser",
)


def fetch_html(
    page,
    url: str,
    cfg: Config,
    wait_selector: Optional[str] = None,
    source: str = "",
    query: str = "",
    scroll_rounds: int = 0,
) -> str:
    """レート制限つきでURLを開いてHTMLを返す。

    - ページ自体が開けない(ネットワーク/ナビゲーション失敗)→ max_retries 回リトライ
    - ページは開けたが wait_selector が現れない → リトライしても改善しない
      (bot チャレンジか DOM 変更)ため、その時点の HTML を即返す。
      パーサ側で「0件 + エラー」として可視化され、debug 保存の対象にもなる
    """
    max_retries = int(cfg.get("scrape.max_retries", 2))
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        polite_sleep(cfg)
        try:
            page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            last_err = e
            logger.warning(
                "fetch failed (%s, attempt %d/%d): %s", url, attempt + 1, max_retries + 1, e
            )
            continue
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, state="attached")
            except Exception:
                html = page.content()
                _log_page_diagnosis(url, wait_selector, html)
                _maybe_dump_html(cfg, source, f"{query}_noselector", html)
                return html
        else:
            # SPA系サイトの描画待ち
            page.wait_for_timeout(1500)
        # 遅延読み込みサイト用: 数回スクロールして下方のセルも描画させる
        for _ in range(max(0, scroll_rounds)):
            try:
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                page.wait_for_timeout(700)
            except Exception:
                break
        html = page.content()
        _maybe_dump_html(cfg, source, query, html)
        return html
    raise RuntimeError(f"fetch failed after {max_retries + 1} attempts: {url}") from last_err


def _log_page_diagnosis(url: str, wait_selector: str, html: str) -> None:
    """セレクタ不在時に「ブロックされたのか DOM が変わったのか」を切り分けるログ。"""
    lower = html.lower()
    title_m = re.search(r"<title[^>]*>(.*?)</title>", lower, re.DOTALL)
    title = (title_m.group(1).strip()[:80] if title_m else "(no title)")
    markers = [m for m in _CHALLENGE_MARKERS if m in lower]
    logger.warning(
        "selector '%s' not found on %s (len=%d, title=%r, challenge_markers=%s)"
        " — bot検知 or DOM変更の可能性",
        wait_selector, url, len(html), title, markers or "none",
    )


def _maybe_dump_html(cfg: Config, source: str, query: str, html: str) -> None:
    """debug_html_dir(環境変数 CARDGAP_DEBUG_HTML_DIR が優先)が設定されていれば
    取得HTMLを保存(セレクタ調査用)。"""
    dump_dir = os.environ.get("CARDGAP_DEBUG_HTML_DIR") or cfg.get("scrape.debug_html_dir", "")
    if not dump_dir:
        return
    out = cfg.resolve_path(dump_dir)
    out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z_-]+", "_", f"{source}_{query}")[:80]
    (out / f"{safe}_{int(time.time())}.html").write_text(html, encoding="utf-8")
