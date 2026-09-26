# eBay相場だけを自宅PCで収集するスクリプト(Windows)。
#
# 背景: クラウド(GitHub Actions)のIPはeBayのbot検知にブロックされるため、
# eBay Sold相場の収集は住宅IPのPCから行う(クラウド側はeBayを試行しない設定)。
# メルカリ収集・サイト更新はクラウドが全自動で続けるので、これを週2〜3回
# (毎日ならベスト)実行するだけでよい。1日50クエリの枠はこのPC実行に全振りされている。
#
# 0件だったとき: 取得ページを debug-html-local ブランチへ自動送信するので、
#           Claudeに「eBayローカル実行が0件だった」と伝えれば実物を見て直せる。
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
$env:CARDGAP_DEBUG_HTML_DIR = "debug_html_local"   # 診断用に取得ページを保存
if (Test-Path "debug_html_local") {
    try { Remove-Item -Recurse -Force "debug_html_local" } catch { }
}
python -m cardgap.pipeline --sources ebay
if ($LASTEXITCODE -ne 0) { exit 1 }

# 自己診断: 直近のeBay実行が「クエリは投げたのに0件」なら、bot検知かページ構造の
# 変更の可能性が高い。取得ページを debug-html-local ブランチに送っておくと、
# 開発側(Claude)がクラウドから実物のHTMLを見てパーサを直せる。
# メモ: PowerShell 5.1 はネイティブコマンドへの引数に含まれる二重引用符を
# 正しく渡せないため、Pythonコード内の文字列はすべて単引用符にしてある
$stats = python -c "import sqlite3;r=sqlite3.connect('cardgap.db').execute('SELECT items_found, queries_total FROM scrape_runs WHERE source=? ORDER BY id DESC LIMIT 1',('ebay',)).fetchone();print('%d %d'%(r[0],r[1]) if r else '0 0')"
if (-not $stats) { $stats = "0 0" }
$parts = "$stats".Trim() -split " "
if ($parts[0] -eq "0" -and $parts.Count -ge 2 -and $parts[1] -ne "0") {
    Write-Host "⚠ eBayの取得が0件でした(bot検知かページ構造変更の可能性)。"
    $hasDebug = (Test-Path "debug_html_local") -and ((Get-ChildItem "debug_html_local" | Measure-Object).Count -gt 0)
    if ($hasDebug) {
        Write-Host "  取得ページを debug-html-local ブランチへ送ります(診断用)..."
        $remote = git remote get-url origin
        Push-Location "debug_html_local"
        # 各ステップの成否を確認しながら進める(git init が失敗したまま add/commit を
        # 走らせると、親のCardGapリポジトリに誤コミットしてしまうため)
        git init -q
        if ($LASTEXITCODE -eq 0) { git symbolic-ref HEAD refs/heads/debug-html-local }
        if ($LASTEXITCODE -eq 0) { git add -A }
        if ($LASTEXITCODE -eq 0) {
            $stamp = Get-Date -Format "yyyy-MM-ddTHH:mm"
            git -c user.name=cardgap-local -c user.email=cardgap-local@localhost commit -qm "local debug html $stamp"
        }
        if ($LASTEXITCODE -eq 0) { git push -qf $remote debug-html-local }
        $pushOk = ($LASTEXITCODE -eq 0)
        Pop-Location
        if ($pushOk) {
            Write-Host "  送信完了。Claudeに「eBayローカル実行が0件だった」と伝えてください。"
            try { Remove-Item -Recurse -Force "debug_html_local" } catch { }
        } else {
            Write-Host "  送信に失敗しました(権限/ネットワーク)。debug_html_local フォルダを残してあります。"
        }
    } else {
        Write-Host "  (取得ページが保存されていないため診断データはありません。ネットワーク断の可能性)"
    }
} elseif (Test-Path "debug_html_local") {
    try { Remove-Item -Recurse -Force "debug_html_local" } catch { }   # 正常時は残さない
}

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
