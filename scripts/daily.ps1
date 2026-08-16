﻿# CardGap 日次バッチ実行スクリプト(自宅PC: Windows タスクスケジューラ用)。
#
# タスクスケジューラ登録例(毎朝 7:00):
#   プログラム: powershell
#   引数:       -ExecutionPolicy Bypass -File C:\path\to\CardGap\scripts\daily.ps1
#
# 流れは scripts/daily.sh と同じ:
#   git pull --rebase → python -m cardgap.pipeline → site/public/data の差分を commit & push
#   (push を受けて GitHub Actions がサイトを再ビルドし GitHub Pages が更新される)
$ErrorActionPreference = "Stop"

# 外部コマンド(git / python)の失敗を検知して非0で終了するヘルパ
function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: CardGap daily failed at '$Step' (exit=$LASTEXITCODE) $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        exit 1
    }
}

# リポジトリ直下へ移動(このスクリプトは <repo>\scripts\ に置かれている前提)
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "=== CardGap daily start: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="

# venv があれば有効化(タスクスケジューラは venv を知らないため)
$venvActivate = Join-Path ".venv" "Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

# サイト側の変更を取り込む。コンフリクト等で失敗したら手動解決が必要なので中断
git pull --rebase origin main
Assert-LastExitCode "git pull --rebase"

# 日次バッチ本体(export.enabled=true なら site/public/data へ JSON も書き出す)
python -m cardgap.pipeline
Assert-LastExitCode "python -m cardgap.pipeline"

# サイト用 JSON に差分があれば commit & push
git add site/public/data
Assert-LastExitCode "git add"

git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "site/public/data に変更なし。commit/push をスキップ"
} else {
    $today = Get-Date -Format "yyyy-MM-dd"
    git commit -m "data: $today 日次データ更新"
    Assert-LastExitCode "git commit"
    git push origin main
    Assert-LastExitCode "git push"
}

Write-Host "=== CardGap daily done: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="
