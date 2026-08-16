"""eBay落札データの相場集計。"""

from __future__ import annotations

import statistics
from typing import Optional, Sequence

from .models import RELIABILITY_LOW, RELIABILITY_OK, MarketStats


def compute_market_stats(
    totals_usd: Sequence[float], min_sold_count: int
) -> Optional[MarketStats]:
    """落札総額(本体+送料 USD)のリストから中央値・件数・最安・最高を集計。

    データ0件なら None。件数が min_sold_count 未満なら reliability='low'。
    """
    values = [v for v in totals_usd if v is not None and v > 0]
    if not values:
        return None
    return MarketStats(
        median_usd=round(statistics.median(values), 2),
        count=len(values),
        min_usd=round(min(values), 2),
        max_usd=round(max(values), 2),
        reliability=RELIABILITY_OK if len(values) >= min_sold_count else RELIABILITY_LOW,
    )
