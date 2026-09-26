#!/usr/bin/env bash
# eBay相場だけを自宅PCで収集するスクリプト(Mac / Linux)。
#
# 背景: クラウド(GitHub Actions)のIPはeBayのbot検知にブロックされるため、
# eBay Sold相場の収集は住宅IPのPCから行う(クラウド側はeBayを試行しない設定)。
# メルカリ収集・サイト更新はクラウドが全自動で続けるので、これを週2〜3回
# (毎日ならベスト)実行するだけでよい。1日50クエリの枠はこのPC実行に全振りされている。
#
# やること: 最新DB取得 → eBayだけスクレイプ → 相場集計・損益計算・通知 →
#           サイト用JSON生成 → commit & push(pushを受けてサイトが自動更新される)
# 0件だったとき: 取得ページを debug-html-local ブランチへ自動送信するので、
#           Claudeに「eBayローカル実行が0件だった」と伝えれば実物を見て直せる。
#
# 使い方:   ./scripts/ebay_local.sh
# 自動化:   crontab -e で例えば「0 21 * * * /path/to/CardGap/scripts/ebay_local.sh >> ~/cardgap_ebay.log 2>&1」
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "[1/3] 最新データを取得..."
git pull --rebase origin main

echo "[2/3] eBay相場を収集(数分かかります。1日50クエリ上限は自動管理)..."
export CARDGAP_DEBUG_HTML_DIR="debug_html_local"   # 診断用に取得ページを保存
rm -rf debug_html_local
python -m cardgap.pipeline --sources ebay

# 自己診断: 直近のeBay実行が「クエリは投げたのに0件」なら、bot検知かページ構造の
# 変更の可能性が高い。取得ページを debug-html-local ブランチに送っておくと、
# 開発側(Claude)がクラウドから実物のHTMLを見てパーサを直せる。
EBAY_STATS=$(python -c 'import sqlite3;r=sqlite3.connect("cardgap.db").execute("SELECT items_found, queries_total FROM scrape_runs WHERE source=? ORDER BY id DESC LIMIT 1",("ebay",)).fetchone();print("%d %d"%(r[0],r[1]) if r else "0 0")' 2>/dev/null || echo "0 0")
EBAY_ITEMS=${EBAY_STATS% *}
EBAY_QUERIES=${EBAY_STATS#* }
if [ "${EBAY_ITEMS:-0}" = "0" ] && [ "${EBAY_QUERIES:-0}" != "0" ]; then
  echo "⚠ eBayの取得が0件でした(bot検知かページ構造変更の可能性)。"
  if [ -d debug_html_local ] && [ -n "$(ls -A debug_html_local 2>/dev/null)" ]; then
    echo "  取得ページを debug-html-local ブランチへ送ります(診断用)..."
    REMOTE_URL=$(git remote get-url origin)
    # メモ: && で連結しているのは、途中で失敗したとき(古いgit等)に後続の
    # add/commit が「親のCardGapリポジトリ」に誤爆するのを防ぐため。
    # git init -b は git 2.28 未満に無いので symbolic-ref で孤立ブランチを作る
    if (
      cd debug_html_local &&
      git init -q &&
      git symbolic-ref HEAD refs/heads/debug-html-local &&
      git add -A &&
      git -c user.name="cardgap-local" -c user.email="cardgap-local@localhost" \
        commit -qm "local debug html $(date +%Y-%m-%dT%H:%M)" &&
      git push -qf "$REMOTE_URL" debug-html-local
    ); then
      echo "  送信完了。Claudeに「eBayローカル実行が0件だった」と伝えてください。"
      rm -rf debug_html_local
    else
      echo "  送信に失敗しました(権限/ネットワーク)。debug_html_local/ を残してあります。"
    fi
  else
    echo "  (取得ページが保存されていないため診断データはありません。ネットワーク断の可能性)"
  fi
else
  rm -rf debug_html_local   # 正常時は診断用HTMLを残さない
fi

echo "[3/3] 結果をpush..."
git add cardgap.db site/public/data
if git diff --cached --quiet; then
  echo "変更なし(本日のeBayクエリ上限に達している場合もこれになります)"
  exit 0
fi
git commit -m "data: eBay相場更新(ローカル実行) $(date +%Y-%m-%dT%H:%M)"
for i in 1 2 3 4; do
  git push origin main && break
  git pull --rebase origin main
  sleep 3
done
echo "完了。数分後にサイトへ反映されます: https://tamago-plants.github.io/CardGap/"
