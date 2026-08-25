# eBay相場だけを自宅PCで収集するスクリプト(Windows)。
#
# 背景: クラウド(GitHub Actions)のIPはeBayのbot検知にブロックされるため、
# eBay Sold相場の収集だけは住宅IPのPCから行う。メルカリ収集・サイト更新は
# クラウド側が全自動で続けるので、これを週2〜3回(毎日ならベスト)実行するだけでよい。
#
# 使い方:   powershell -ExecutionPolicy Bypass -File scripts\ebay_local.ps1
# 自動化:   タスクスケジューラで毎晩1回登録(README「日次実行のセットアップ」参照)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (Test-Path ".venv\Scripts\Activate.ps1") {
    . ".venv\Scripts\Activate.ps1"
}

Write-Host "[1/3] 最新データを取得..."
git pull --rebase origin main
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "[2/3] eBay相場を収集(数分かかります。1日50クエリ上限は自動管理)..."
python -m cardgap.pipeline --sources ebay
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "[3/3] 結果をpush..."
git add cardgap.db site/public/data
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "変更なし(本日のeBayクエリ上限に達している場合もこれになります)"
    exit 0
}
$stamp = Get-Date -Format "yyyy-MM-ddTHH:mm"
git commit -m "data: eBay相場更新(ローカル実行) $stamp"
foreach ($i in 1..4) {
    git push origin main
    if ($LASTEXITCODE -eq 0) { break }
    git pull --rebase origin main
    Start-Sleep -Seconds 3
}
Write-Host "完了。数分後にサイトへ反映されます: https://tamago-plants.github.io/CardGap/"
