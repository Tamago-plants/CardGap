"""CardGap Streamlit ダッシュボード。

起動方法:
    cd cardgap && streamlit run dashboard/app.py

方針:
  - データアクセスは cardgap.db の関数経由に統一する(UIから直接SQLを書かない)。
    例外として db.py に無い「eBay落札履歴の全期間表示」のみ、本ファイル内の
    fetch_ebay_history() で最小限のSQLを書く。
  - SQLite接続はリランごとに新規作成する(st.cache_resource で接続を使い回すと
    Streamlit のスレッドをまたいで sqlite3 がエラーになるため)。
  - データ整形はUIから分離した純関数(deals_to_dataframe 等)にまとめ、
    Streamlit なしでテストできるようにする。
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

# streamlit run はこのファイルを直接実行するため、cardgap パッケージを import できるよう
# プロジェクトルート(config.yaml のあるディレクトリ)を sys.path に追加する
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from cardgap import db  # noqa: E402
from cardgap.config import Config, load_config  # noqa: E402
from cardgap.models import CONF_HIGH, CONF_LOW, CONF_MEDIUM  # noqa: E402

# confidence フィルタの選択肢(表示順)
CONFIDENCE_CHOICES = [CONF_HIGH, CONF_MEDIUM, CONF_LOW]

# ソート順の表示名 → matches の列名
SORT_KEYS = {"利益率": "profit_rate", "利益額": "profit_jpy"}


# ------------------------------------------------------------ データ整形(純関数)

def deal_display_name(row: dict[str, Any]) -> str:
    """deals 行(db.list_deals の dict)からカード表示名を組み立てる。

    models.Card.display_name() と同じ形式: 「名前 番号 セット PSAグレード」。
    """
    parts = [str(row.get("card_name") or "")]
    if row.get("card_number"):
        parts.append(str(row["card_number"]))
    if row.get("set_code"):
        parts.append(str(row["set_code"]))
    if row.get("psa_grade"):
        parts.append(f"PSA{row['psa_grade']}")
    return " ".join(p for p in parts if p)


def deal_option_label(row: dict[str, Any]) -> str:
    """詳細セクションの selectbox 用ラベル。カード名 + 仕入価格で案件を識別する。"""
    return f"{deal_display_name(row)} / {row['source']} ¥{int(row['buy_price_jpy']):,}"


def sort_deals(rows: Sequence[dict[str, Any]], sort_by: str) -> list[dict[str, Any]]:
    """表示名(利益率/利益額)で降順ソートした新しいリストを返す。"""
    key = SORT_KEYS.get(sort_by, "profit_rate")
    return sorted(rows, key=lambda r: float(r[key]), reverse=True)


def deals_to_dataframe(rows: Sequence[dict[str, Any]]) -> pd.DataFrame:
    """deals 行をメインテーブル表示用の DataFrame に変換する。"""
    columns = [
        "画像", "カード名", "仕入元", "仕入価格(¥)", "出品リンク",
        "eBay中央値USD", "eBay件数", "実質利益(¥)", "利益率(%)",
        "confidence", "相場信頼度",
    ]
    records = []
    for r in rows:
        records.append(
            {
                "画像": r.get("image_url"),
                "カード名": deal_display_name(r),
                "仕入元": r["source"],
                "仕入価格(¥)": int(r["buy_price_jpy"]),
                "出品リンク": r["listing_url"],
                "eBay中央値USD": float(r["ebay_median_usd"]),
                "eBay件数": int(r["ebay_count_30d"]),
                "実質利益(¥)": float(r["profit_jpy"]),
                "利益率(%)": round(float(r["profit_rate"]) * 100, 1),
                "confidence": r["confidence"],
                "相場信頼度": r["reliability"],
            }
        )
    return pd.DataFrame(records, columns=columns)


def summarize_deals(rows: Sequence[dict[str, Any]]) -> tuple[int, float, float]:
    """(案件数, 利益率最高, 合計想定利益JPY) を返す。空なら全て0。"""
    if not rows:
        return 0, 0.0, 0.0
    best_rate = max(float(r["profit_rate"]) for r in rows)
    total_profit = sum(float(r["profit_jpy"]) for r in rows)
    return len(rows), best_rate, total_profit


def ebay_history_to_dataframe(rows: Iterable[sqlite3.Row | dict[str, Any]]) -> pd.DataFrame:
    """eBay 落札履歴行を表表示用 DataFrame(sold_at / title / 総額USD / リンク)に変換する。"""
    records = []
    for r in rows:
        total = float(r["price_usd"]) + float(r["shipping_usd"] or 0)
        records.append(
            {
                "sold_at": r["sold_at"],
                "title": r["title"],
                "総額USD": round(total, 2),
                "リンク": r["listing_url"],
            }
        )
    return pd.DataFrame(records, columns=["sold_at", "title", "総額USD", "リンク"])


def ebay_history_chart_data(hist_df: pd.DataFrame) -> pd.DataFrame:
    """sold_at × 総額USD の折れ線グラフ用データ。日付昇順、sold_at 不明の行は除外。"""
    if hist_df.empty:
        return pd.DataFrame()
    chart = hist_df.dropna(subset=["sold_at"]).copy()
    if chart.empty:
        return pd.DataFrame()
    chart["sold_at"] = pd.to_datetime(chart["sold_at"])
    chart = chart.sort_values("sold_at").set_index("sold_at")
    return chart[["総額USD"]]


# ------------------------------------------------------------ DBアクセス(db.py に無い分のみ)

def fetch_ebay_history(conn: sqlite3.Connection, card_id: int) -> list[sqlite3.Row]:
    """指定カードの eBay 落札履歴(全期間、confidence high/medium のみ)。

    db.ebay_sold_for_card() は since_date 必須(直近N日集計用)のため、
    全期間表示だけは例外的にここで最小限のSQLを書く。
    """
    return conn.execute(
        """
        SELECT * FROM listings_ebay_sold
        WHERE card_id = ? AND match_confidence IN ('high', 'medium')
        ORDER BY sold_at DESC
        """,
        (card_id,),
    ).fetchall()


# ------------------------------------------------------------ UI

def _render_sidebar(conn: sqlite3.Connection, cfg: Config) -> dict[str, Any]:
    """サイドバーのフィルタ群を描画して選択値を dict で返す。"""
    # カテゴリはDBから動的に取得(cards テーブルが空なら「全て」のみ)
    categories = sorted({c.category for c in db.list_cards(conn, enabled_only=False)})
    default_rate_pct = int(round(float(cfg.get("threshold.min_profit_rate", 0.20)) * 100))
    with st.sidebar:
        st.header("フィルタ")
        category = st.selectbox("カテゴリ", ["全て"] + categories)
        min_rate_pct = st.slider(
            "最低利益率(%)", min_value=-100, max_value=100, value=default_rate_pct, step=1
        )
        min_profit_jpy = st.number_input("最低利益額(¥)", value=0, step=1000)
        confidences = st.multiselect(
            "confidence", CONFIDENCE_CHOICES, default=CONFIDENCE_CHOICES
        )
        psa_only = st.checkbox("PSAのみ", value=False)
        include_low = st.checkbox("相場信頼度 low を含む", value=True)
        sort_by = st.selectbox("ソート順", list(SORT_KEYS))
    return {
        "category": None if category == "全て" else category,
        "min_profit_rate": min_rate_pct / 100.0,
        "min_profit_jpy": float(min_profit_jpy),
        "confidences": tuple(confidences),
        "psa_only": psa_only,
        "include_low": include_low,
        "sort_by": sort_by,
    }


def _render_metrics(rows: Sequence[dict[str, Any]]) -> None:
    """上部のサマリ metric 3つ。"""
    n, best_rate, total_profit = summarize_deals(rows)
    m1, m2, m3 = st.columns(3)
    m1.metric("案件数", f"{n}件")
    m2.metric("利益率最高", f"{best_rate * 100:.1f}%")
    m3.metric("合計想定利益", f"¥{total_profit:,.0f}")


def _render_deals_table(rows: Sequence[dict[str, Any]]) -> None:
    """メインの案件テーブル。"""
    df = deals_to_dataframe(rows)
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "画像": st.column_config.ImageColumn("画像"),
            "出品リンク": st.column_config.LinkColumn("出品リンク", display_text="出品を開く"),
            "仕入価格(¥)": st.column_config.NumberColumn("仕入価格(¥)", format="¥%d"),
            "eBay中央値USD": st.column_config.NumberColumn("eBay中央値USD", format="$%.2f"),
            "実質利益(¥)": st.column_config.NumberColumn("実質利益(¥)", format="¥%d"),
            "利益率(%)": st.column_config.NumberColumn("利益率(%)", format="%.1f%%"),
        },
    )


def _render_detail(conn: sqlite3.Connection, cfg: Config, rows: Sequence[dict[str, Any]]) -> None:
    """カード詳細セクション: 案件を選んで eBay 落札履歴の表とチャートを表示。"""
    st.subheader("カード詳細")
    idx = st.selectbox(
        "案件を選択",
        options=list(range(len(rows))),
        format_func=lambda i: deal_option_label(rows[i]),
    )
    selected = rows[idx]
    card_id = int(selected["card_id"])

    card = db.get_card(conn, card_id)
    if card is not None:
        st.markdown(f"**{card.display_name()}**({card.category} / {card.name_en})")

    # 無視ボタン: 押したら ignore_list に登録して即リラン(一覧から消える)
    if st.button("この出品を無視"):
        db.add_ignore(
            conn, selected["source"], selected["listing_url"], note=deal_display_name(selected)
        )
        conn.commit()
        st.rerun()

    history = fetch_ebay_history(conn, card_id)
    lookback = int(cfg.get("scrape.ebay_lookback_days", 30))
    since = (date.today() - timedelta(days=lookback)).isoformat()
    recent = db.ebay_sold_for_card(conn, card_id, since)
    st.caption(f"eBay 落札履歴: 全 {len(history)} 件(直近{lookback}日: {len(recent)} 件)")

    hist_df = ebay_history_to_dataframe(history)
    if hist_df.empty:
        st.info("このカードの eBay 落札履歴がありません。")
        return
    st.dataframe(
        hist_df,
        width="stretch",
        hide_index=True,
        column_config={
            "総額USD": st.column_config.NumberColumn("総額USD", format="$%.2f"),
            "リンク": st.column_config.LinkColumn("リンク", display_text="落札ページ"),
        },
    )
    chart = ebay_history_chart_data(hist_df)
    if not chart.empty:
        st.line_chart(chart)


def _render_ignore_manager(conn: sqlite3.Connection) -> None:
    """無視リストの一覧と解除ボタン。"""
    with st.expander("無視リスト管理"):
        ignored = db.list_ignored(conn)
        if not ignored:
            st.caption("無視した出品はありません。")
            return
        for row in ignored:
            col_info, col_btn = st.columns([5, 1])
            note = f"{row['note']} " if row["note"] else ""
            col_info.markdown(f"[{row['source']}] {note}{row['listing_url']}")
            if col_btn.button("解除", key=f"unignore_{row['id']}"):
                db.remove_ignore(conn, row["listing_url"])
                conn.commit()
                st.rerun()


def _render(conn: sqlite3.Connection, cfg: Config) -> None:
    st.title("CardGap ダッシュボード")
    filters = _render_sidebar(conn, cfg)

    if not filters["confidences"]:
        rows: list[dict[str, Any]] = []
    else:
        rows = db.list_deals(
            conn,
            min_profit_rate=filters["min_profit_rate"],
            min_profit_jpy=filters["min_profit_jpy"],
            confidences=filters["confidences"],
            psa_only=filters["psa_only"],
            category=filters["category"],
            include_low_reliability=filters["include_low"],
        )
    rows = sort_deals(rows, filters["sort_by"])

    _render_metrics(rows)

    if not rows:
        # フィルタで消えたのか、そもそもデータが無いのかを分けて案内する
        if db.list_deals(conn):
            st.info("フィルタ条件に合う案件がありません。サイドバーの条件を緩めてください。")
        else:
            st.info("案件データがありません。`python -m cardgap run` を実行してください。")
        _render_ignore_manager(conn)
        return

    _render_deals_table(rows)
    _render_detail(conn, cfg, rows)
    _render_ignore_manager(conn)


def main() -> None:
    st.set_page_config(page_title="CardGap", page_icon="🃏", layout="wide")
    cfg = load_config()
    # 毎リラン新規接続(スレッドをまたいだ sqlite3 接続の使い回しを避ける)
    conn = db.connect(cfg.db_path())
    try:
        _render(conn, cfg)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
