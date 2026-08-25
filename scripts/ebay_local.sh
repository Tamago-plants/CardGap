#!/usr/bin/env bash
# eBay相場だけを自宅PCで収集するスクリプト(Mac / Linux)。
#
# 背景: クラウド(GitHub Actions)のIPはeBayのbot検知にブロックされるため、
# eBay Sold相場の収集だけは住宅IPのPCから行う。メルカリ収集・サイト更新は
# クラウド側が全自動で続けるので、これを週2〜3回(毎日ならベスト)実行するだけでよい。
#
# やること: 最新DB取得 → eBayだけスクレイプ → 相場集計・損益計算・通知 →
#           サイト用JSON生成 → commit & push(pushを受けてサイトが自動更新される)
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
python -m cardgap.pipeline --sources ebay

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
