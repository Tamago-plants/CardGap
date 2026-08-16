#!/usr/bin/env bash
# CardGap 日次バッチ実行スクリプト(自宅PC: Mac / Linux 用)。
#
# cron 登録例(毎朝 7:00、ログ追記):
#   0 7 * * * /path/to/CardGap/scripts/daily.sh >> ~/cardgap_cron.log 2>&1
#
# 流れ:
#   1. git pull --rebase でサイト側(site/)の変更を取り込む(失敗したら中断)
#   2. python -m cardgap.pipeline で日次バッチ一式
#      (スクレイプ → 集計 → Discord通知 → site/public/data/*.json エクスポート)
#   3. JSON に差分があれば commit & push
#      → push を受けて GitHub Actions がサイトを再ビルドし GitHub Pages が更新される
set -euo pipefail

# どこで失敗しても cron のログ(や MAILTO)で気づけるよう ERROR 行を出して非0終了する
trap 'echo "ERROR: CardGap daily failed (exit=$?) at $(date "+%Y-%m-%d %H:%M:%S")" >&2' ERR

# リポジトリ直下へ移動(このスクリプトは <repo>/scripts/ に置かれている前提)
cd "$(dirname "$0")/.."

echo "=== CardGap daily start: $(date '+%Y-%m-%d %H:%M:%S') ==="

# venv があれば有効化(cron は venv を知らないため)
if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

# サイト側の変更を取り込む。コンフリクト等で失敗したら手動解決が必要なので中断
if ! git pull --rebase origin main; then
    echo "ERROR: git pull --rebase failed. コンフリクトを手動で解決してから再実行してください。" >&2
    exit 1
fi

# 日次バッチ本体(export.enabled=true なら site/public/data へ JSON も書き出す)
python -m cardgap.pipeline

# サイト用 JSON に差分があれば commit & push
git add site/public/data
if git diff --cached --quiet; then
    echo "site/public/data に変更なし。commit/push をスキップ"
else
    git commit -m "data: $(date +%F) 日次データ更新"
    git push origin main
fi

echo "=== CardGap daily done: $(date '+%Y-%m-%d %H:%M:%S') ==="
