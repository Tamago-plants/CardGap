"""config.yaml の読み込み。プロジェクトルート(cardgap/ ディレクトリ)基準でパスを解決する。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# cardgap パッケージの1つ上 = プロジェクトルート(config.yaml / data/ がある場所)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


class Config:
    """dict のラッパ。cfg.get("ebay_fees.final_value_fee") のようにドット区切りで参照できる。"""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def raw(self) -> dict[str, Any]:
        return self._data

    # --- よく使う値のヘルパ ---

    def db_path(self) -> Path:
        p = Path(self.get("app.db_path", "cardgap.db"))
        return p if p.is_absolute() else PROJECT_ROOT / p

    def resolve_path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def discord_webhook_url(self) -> str:
        return os.environ.get("DISCORD_WEBHOOK_URL") or self.get("discord.webhook_url", "") or ""

    def enabled_categories(self) -> dict[str, dict[str, Any]]:
        cats = self.get("categories", {}) or {}
        return {k: v for k, v in cats.items() if (v or {}).get("enabled", True)}


def load_config(path: str | Path | None = None) -> Config:
    cfg_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    with open(cfg_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config(data)
