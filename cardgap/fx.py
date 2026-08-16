"""USD/JPY レート取得。無料API(open.er-api.com)→ DB保存 → 失敗時は前回値。"""

from __future__ import annotations

import logging
import sqlite3

import requests

from . import db
from .config import Config

logger = logging.getLogger(__name__)


def fetch_usd_jpy_from_api(api_url: str, timeout: float = 15.0) -> float:
    """open.er-api.com 形式のレスポンスから JPY レートを取り出す。"""
    resp = requests.get(api_url, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    rate = data.get("rates", {}).get("JPY")
    if not rate or rate <= 0:
        raise ValueError(f"API response has no JPY rate: {api_url}")
    return float(rate)


def get_usd_jpy(cfg: Config, conn: sqlite3.Connection, refresh: bool = True) -> float:
    """レート取得の優先順位: API(成功したらDB保存)→ DBの前回値 → config のフォールバック。"""
    if refresh:
        try:
            rate = fetch_usd_jpy_from_api(cfg.get("fx.api_url"))
            db.save_fx_rate(conn, "USDJPY", rate)
            conn.commit()
            logger.info("USD/JPY rate fetched: %.2f", rate)
            return rate
        except Exception as e:  # ネットワーク/形式エラーは前回値に落とす
            logger.warning("FX API failed (%s), falling back to last stored rate", e)
    stored = db.latest_fx_rate(conn, "USDJPY")
    if stored:
        return stored
    fallback = float(cfg.get("fx.fallback_rate", 150.0))
    logger.warning("No stored FX rate; using fallback %.2f", fallback)
    return fallback
