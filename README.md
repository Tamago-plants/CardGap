# CardGap

eBay の Sold(落札済み)相場と、メルカリ / スニーカーダンク(スニダン)の販売価格を毎日突き合わせ、
「日本で安く仕入れて eBay で売ると利益が出るカード」を検出して Discord に通知するツール。
結果は **Web ダッシュボード(GitHub Pages)** で閲覧でき、**Discord 日次ダイジェスト**
(昨日のまとめ・ランキング・騰落)も毎日届く。

- 対象: ポケモンカード、NARUTO カードゲーム / ナルティメットデータカードダス(カテゴリは追加可能)
- やること: スクレイプ → 同一カードマッチング → 相場集計 → 損益計算 → Web ダッシュボード表示 / Discord 通知(新着案件 + 日次ダイジェスト)
- **やらないこと: 自動購入・自動入札・自動出品。検出と通知まで**

## アーキテクチャ

**クラウド完結**。GitHub Actions が日次バッチを 1 日 4 回実行して DB と JSON を commit し、
サイトを再ビルドして GitHub Pages が更新される(PC 不要・サーバ不要・運用費 0 円)。
ローカル PC からの実行(scripts/daily.sh)にもいつでも切り替えられる。

```
GitHub Actions(.github/workflows/scrape.yml、JST 7/11/15/19時)
  ├─ python -m cardgap.pipeline
  │    スクレイプ → 相場集計 → 損益計算 → Discord通知 → site/public/data/*.json
  └─ cardgap.db + JSON を commit & push → deploy-pages.yml を起動
        │
        ▼
GitHub Actions(.github/workflows/deploy-pages.yml)
  └─ site/ を npm ci && npm run build
        │
        ▼
GitHub Pages(https://tamago-plants.github.io/CardGap/)
  └─ React サイト: ダッシュボード・ランキング・市場マップ・案件スクリーナー
```

## ⚠ 利用上の注意

- 各サイト(eBay / メルカリ / スニダン)の利用規約の範囲内で、**個人利用・低頻度アクセス**に限定すること。
  - リクエスト間に 2〜5 秒のランダムディレイを必ず挟む(`browser.fetch_html()` が強制)
  - eBay 検索は 1 日 50 クエリ上限(`scrape.max_ebay_queries_per_day`)
- スクレイピングは自己責任。アカウント制限・IP ブロック等のリスクを理解した上で使うこと。
- 各サイトの DOM 変更でパーサは壊れる前提の設計になっている(壊れても他ソースは動き続け、失敗は
  `scrape_runs` テーブルと Discord 通知で可視化される)。直し方は「制約・既知のリスク」参照。

## セットアップ

Python 3.11 以上が必要。**コマンドはすべてリポジトリ直下(このファイルがある場所)で実行する。**

```bash
git clone https://github.com/Tamago-plants/CardGap.git
cd CardGap
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium     # スクレイプ用ブラウザ
python -m cardgap initdb        # DB作成 + data/watchlist.csv 取込
```

Discord 通知を使う場合は Webhook URL を環境変数で渡す(`config.yaml` の `discord.webhook_url` でも可。
環境変数が優先される):

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/XXXX/YYYY"
python -m cardgap notify --test   # 疎通確認
```

## 使い方

### メインCLI(`python -m cardgap`)

```bash
python -m cardgap initdb                  # DB初期化 + watchlist取込(watchlist変更後も再実行)
python -m cardgap fx                      # USD/JPY レート更新
python -m cardgap match                   # DB内データだけで相場集計・損益再計算(スクレイプなし)
python -m cardgap deals                   # 上位案件を表示
python -m cardgap deals --min-rate 0.3 --min-profit 10000 --psa-only --limit 10
python -m cardgap notify --test           # Discord疎通テスト
python -m cardgap notify                  # match相当を実行して閾値超え案件を通知
python -m cardgap run                     # 日次バッチ一式(= python -m cardgap.pipeline)
python -m cardgap export                  # サイト用JSON(deals/history/summary)を書き出す
python -m cardgap export --out /tmp/data  # 出力先を指定(既定: config の export.output_dir)
python -m cardgap digest                  # Discord日次ダイジェストを今すぐ送る
```

共通オプション `--config <path>` で `config.yaml` 以外の設定ファイルを指定できる。

### スクレイパー単体(`python -m cardgap.scrape`)

動作確認・セレクタ調査用。source は `ebay` / `mercari` / `snkrdunk`。

```bash
# クエリを直接指定して1回だけ実行(結果はJSONで標準出力)
python -m cardgap.scrape ebay --query "charizard s12a 201/190"
python -m cardgap.scrape mercari --query "リザードン 201/190" --store   # --store でDB保存も行う

# 保存済みHTMLをパースする(ネットワーク・ブラウザ不要。パーサ修正時の確認に便利)
python -m cardgap.scrape ebay --from-html tests/fixtures/ebay_sold_sample.html
python -m cardgap.scrape mercari --from-html tests/fixtures/mercari_search_sample.html
python -m cardgap.scrape snkrdunk --from-html tests/fixtures/snkrdunk_search_sample.html

# watchlist 全件で本番同様に実行(DB保存あり)。--limit でクエリ数を絞る
python -m cardgap.scrape ebay --watchlist --limit 3
```

### ローカルダッシュボード(Streamlit)

```bash
streamlit run dashboard/app.py
```

案件一覧(フィルタ・ソート)、カード別の eBay 落札履歴チャート、出品の「無視」登録/解除ができる。
閲覧だけなら Web ダッシュボード(GitHub Pages)でも見られるが、「無視」登録は DB を直接触る
Streamlit 側でのみ可能。

## Webサイトのセットアップ

サイト(`site/`、React + Vite)は GitHub Actions(`.github/workflows/deploy-pages.yml`)が
ビルドして GitHub Pages で公開する。初回のみ以下の設定が必要:

1. リポジトリを **Public** にする(Settings > General > Change visibility)。
   GitHub Pages を無料枠で使うための前提
2. **Settings > Pages > Source** を「**GitHub Actions**」にする
3. あとは main に push すると自動デプロイされる(`site/**` 配下の変更が対象。
   日次バッチの JSON push でも再ビルドされる)。公開 URL:
   **https://tamago-plants.github.io/CardGap/**
4. ローカル開発: `cd site && npm install && npm run dev`
   (`python -m cardgap export` を先に実行しておくと実データで確認できる)

## 自動実行(クラウド完結・既定)

**PC 不要の運用**。`.github/workflows/scrape.yml` が GitHub Actions 上で日次バッチを
1 日 4 回(JST 7:00 / 11:00 / 15:00 / 19:00)実行し、`cardgap.db` と `site/public/data`
を自動 commit → サイト再デプロイまで行う。

- **Discord 通知を使う場合**: リポジトリの Settings > Secrets and variables > Actions >
  New repository secret で `DISCORD_WEBHOOK_URL` を登録する(日次ダイジェストは 1 日 1 回だけ送信される)
- **実行回数の変更**: `scrape.yml` の `cron` を編集(UTC 表記。JST−9 時間)。
  eBay のクエリ上限は DB の実行ログで日単位管理されるため、回数を増やしても上限は超えない
- **手動実行**: Actions タブ > Scheduled scrape > Run workflow
- **停止**: Actions タブ > Scheduled scrape > 右上「…」> Disable workflow
- ⚠ **制約**: GitHub ランナーはデータセンター IP のため、eBay/メルカリの bot 検知に
  自宅回線より引っかかりやすい。成功率はダッシュボードの収集ステータスと Discord 通知で
  監視し、失敗が続く場合は下記のローカル実行に切り替える
- `cardgap.db` は Actions が commit するため追跡対象になっている。ローカルで作業する
  ときは実行前に `git pull` して最新の DB を取り込むこと

## eBay相場の収集(自宅PCで実行・ハイブリッド運用)

クラウド(GitHub Actions)の IP は eBay の bot 検知にブロックされるため、
**eBay Sold 相場の収集だけは自宅 PC から実行する**(メルカリ収集・集計・サイト更新・
通知はクラウドが全自動で継続する)。

### 初回セットアップ(1回だけ、約5分)

```bash
git clone https://github.com/Tamago-plants/CardGap.git
cd CardGap
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 実行(週2〜3回。毎日ならベスト)

```bash
./scripts/ebay_local.sh                                          # Mac / Linux
powershell -ExecutionPolicy Bypass -File scripts\ebay_local.ps1  # Windows
```

最新DBの取得 → eBayスクレイプ(1日50クエリ上限は自動管理)→ 相場集計・損益計算・
Discord通知 → サイト用JSON生成 → push まで一括で行う。push を受けてサイトが自動更新される。
Discord 通知を出したい場合は実行前に `DISCORD_WEBHOOK_URL` を設定しておく。

cron / タスクスケジューラに登録すれば PC 起動中は全自動(登録例は次節と同じ要領で、
スクリプトを `ebay_local.sh` / `ebay_local.ps1` にする)。

## 日次実行のセットアップ(ローカル実行に切り替える場合)

日次バッチは `scripts/daily.sh`(Mac / Linux)/ `scripts/daily.ps1`(Windows)経由で実行する。
どちらも「`git pull --rebase` → `python -m cardgap.pipeline` → `site/public/data` の差分を
commit & push」まで行う(push を受けて GitHub Actions がサイトを自動デプロイする)。
`.venv` があれば自動で有効化するので、venv のフルパス指定は不要。

- バッチの流れ: watchlist 取込 → 為替更新 → eBay / メルカリ / スニダン スクレイプ →
  相場集計 + 損益計算(`matches` 再構築) → Discord 通知(新着案件 + 日次ダイジェスト) →
  サイト用 JSON エクスポート。1 ソースが全滅しても他ソースは続行する
- 失敗時は非 0 で終了し、ログに `ERROR:` 行が出る(cron の `MAILTO` を設定していればメールでも気づける)

### cron(Mac / Linux)

毎朝 7:00 に実行し、ログを追記する例(`crontab -e`):

```cron
0 7 * * * /path/to/CardGap/scripts/daily.sh >> ~/cardgap_cron.log 2>&1
```

### Windows(タスクスケジューラ)

タスクスケジューラで「タスクの作成」→ トリガー「毎日 7:00」→ 操作「プログラムの開始」で登録:

```
プログラム/スクリプト: powershell
引数の追加:            -ExecutionPolicy Bypass -File C:\path\to\CardGap\scripts\daily.ps1
```

### DISCORD_WEBHOOK_URL の設定

Discord 通知・日次ダイジェストを使う場合は Webhook URL を環境変数で渡す
(`config.yaml` の `discord.webhook_url` に直接書いてもよいが、環境変数が優先される):

- **cron**: crontab の先頭(コマンド行より上)で変数を定義する

  ```cron
  DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/XXXX/YYYY
  0 7 * * * /path/to/CardGap/scripts/daily.sh >> ~/cardgap_cron.log 2>&1
  ```

- **Windows**: ユーザー環境変数に `DISCORD_WEBHOOK_URL` を追加する
  (設定 > システム > バージョン情報 > システムの詳細設定 > 環境変数)

## config.yaml 解説

| セクション | キー | 意味 |
|---|---|---|
| `app` | `db_path` | SQLite ファイルパス(`cardgap/` からの相対) |
| | `log_level` | ログレベル(`INFO` 等) |
| `categories.<名前>` | `enabled` | カテゴリの有効/無効。無効カテゴリは watchlist 取込・スクレイプ対象外 |
| | `names_csv` | 日英対訳辞書 CSV のパス |
| | `snkrdunk` | スニダンに商品マスタがあるカテゴリのみ `true`(ナルトは `false`) |
| `fx` | `api_url` | 為替 API(open.er-api.com、無料・キー不要) |
| | `conversion_margin` | 出金時の為替マージン(Payoneer 等)。既定 2% |
| | `fallback_rate` | API 失敗かつ DB にレートが無い場合の最終フォールバック |
| `ebay_fees` | `final_value_fee` | トレカカテゴリの FVF 13.25% |
| | `per_order_fee_usd` | 注文ごとの固定手数料 $0.30 |
| | `international_fee` | 日本セラーの海外決済手数料 1.35% |
| | `promoted_listing` | 広告費想定 2%。使わないなら 0 |
| `shipping` | `default_out_jpy` | eBay 発送送料(eLogi/FedEx 想定の平均)。買い手負担なら 0 |
| `buy_side` | `mercari_fee_rate` | メルカリ購入側手数料率(なし = 0) |
| | `mercari_shipping_jpy` | メルカリ仕入送料(送料込み前提 = 0) |
| | `snkrdunk_buyer_fee_rate` | スニダン購入手数料率(既定 5.5%。**要実額確認**) |
| | `snkrdunk_shipping_jpy` | スニダン仕入送料 |
| `threshold` | `min_profit_jpy` | 通知する最低利益額 |
| | `min_profit_rate` | 通知する最低利益率 |
| | `min_sold_count_30d` | eBay 直近 30 日の落札件数がこれ未満なら相場信頼度 `low` |
| `scrape` | `delay_min_s` / `delay_max_s` | リクエスト間のランダムディレイ範囲(秒) |
| | `max_retries` | 取得失敗時のリトライ回数 |
| | `max_ebay_queries_per_day` | eBay 検索の 1 日上限(bot 検知対策) |
| | `ebay_lookback_days` | 相場集計の対象期間(日) |
| | `headless` | ブラウザをヘッドレスで起動するか |
| | `timeout_ms` | ページ取得タイムアウト |
| | `debug_html_dir` | 空以外にすると取得 HTML をそのディレクトリに保存(セレクタ調査用) |
| | `chromium_executable` | Playwright 同梱以外の Chromium/Chrome を使う場合の実行ファイルパス(環境変数 `CARDGAP_CHROMIUM_PATH` が優先) |
| `discord` | `webhook_url` | Webhook URL(環境変数 `DISCORD_WEBHOOK_URL` が優先) |
| | `max_deals_per_message` | 1 メッセージあたりの案件数(Discord 上限の 10 で頭打ち) |
| | `daily_digest` | 日次ダイジェスト(昨日のまとめ・ランキング・騰落)を送るか。`python -m cardgap digest` は設定に関係なく強制送信 |
| `export` | `enabled` | サイト用 JSON エクスポートの有効/無効(日次バッチの最後に実行) |
| | `output_dir` | `deals.json` / `history.json` / `summary.json` の出力先(既定 `site/public/data`) |
| | `history_days` | `history.json`(価格推移チャート)に含める日数 |
| | `top_n` | `summary.json` のランキング(利益率順・利益額順)件数 |
| | `movers_n` | 騰落(上昇/下落)の表示件数 |
| | `site_url` | Discord 日次ダイジェストに載せるダッシュボードの URL(空なら省略) |

## データファイル(data/)

### watchlist.csv(監視カード一覧)

1 行 = 監視カード 1 件。ヘッダは日本語・英語どちらでも可(UTF-8、BOM 付き可)。

| 列(日本語ヘッダ) | 英語ヘッダ | 意味 |
|---|---|---|
| カテゴリ | `category` | `pokemon` / `naruto` など(config.yaml の categories と対応) |
| 日本語名 | `name_ja` | メルカリ / スニダン検索に使う |
| 英語名 | `name_en` | eBay 検索に使う |
| セット記号 | `set_code` | 例 `s12a`。カードダス等は空欄可 |
| カード番号 | `card_number` | `201/190`(ポケカ)/ `DN-001`・`忍-001`(シリーズ番号)/ `DN-*`(**シリーズ監視**、下記) |
| PSAグレード指定 | `psa_grade` | 例 `10`。**空欄 = 生カード(raw)** |
| 有効フラグ | `enabled` | `1`/`0`(`true`/`false`/`はい` 等も可)。0 の行は取込されるがスクレイプ対象外 |

編集後は `python -m cardgap initdb` で再取込する。

### pokemon_names.csv / naruto_names.csv(日英対訳辞書)

ヘッダ `name_ja,name_en`、1 行 1 キャラ。カード番号がタイトルに無い出品を「名前のみ一致(low)」で
拾うための表記ゆれ対策に使う。

### シリーズ監視(ナルト系の相場収集はこれが基本)

`カード番号` を `DN-*` のように書くと、その 1 行で**シリーズ全体**を監視できる:

- eBay Sold をプレフィックス(例 `Naruto Data Carddass Japanese DN`)で 1 クエリ検索し、
  タイトルから `DN-001` 形式の番号と PSA グレードを抽出して、
  **見つかった番号ごとにカードを自動登録**して相場を蓄積する(confidence は high)
- 自動登録されたカードは個別の検索クエリを発行しない(eBay の日次上限を消費しない)。
  特定の番号を重点的に追いたくなったら、その番号の行(例 `DN-001`)を watchlist に
  追加すれば通常の監視カードに昇格する
- 対応する番号体系: ナルティメットデータカードダスの `DN-001` / `NM-001` / `NX-001`
  (プロモ等の変則プレフィックスも `DNP-*` のように行を足せば拾える)、
  旧 NARUTO カードゲームの `忍-001`(漢字プレフィックス)
- 初期データにはこの 4 シリーズの監視行が有効状態で入っている

注意: コンディション表記の `NM`(Near Mint)と誤認しないよう、シリーズ番号は
**2 桁以上の数字**(例 `DN-01`〜)のみ番号として扱う。

### キーワード監視(未開封BOX・プロモなど番号の無い商品)

`カード番号` と `セット記号` を**空欄**にすると、名前(日本語名/英語名)の
**全単語がタイトルに含まれるか**(語順不問)で判定するキーワード監視になる。
一致した出品は confidence `medium`(番号が存在しない商品では名前一致が最良の判定のため)。

```csv
naruto,ナルト カードダス BOX 未開封,Naruto Carddass Box Sealed,,,,1
naruto,ナルト カードダス プロモ,Naruto Carddass Promo,,,,1
```

- 日本語名はメルカリ/スニダン検索とタイトル判定、英語名は eBay 検索とタイトル判定に使われる
- 語を増やすほど絞り込みは強くなるが取りこぼしも増える。まとめ売りや別商品の混入が
  多い場合は語を足して調整する(例: `シュリンク` を足す)
- 初期データにナルト系の BOX 2種・プロモ 1種のキーワード監視行が入っている

### カテゴリ追加方法

1. `config.yaml` の `categories` にカテゴリを追加(`names_csv` のパスと `snkrdunk` の有無を指定)
2. `data/<カテゴリ>_names.csv` を作成(ヘッダ `name_ja,name_en`)
3. `data/watchlist.csv` に該当カテゴリの行を追記して `python -m cardgap initdb`

## 仕組み

### DB スキーマ(SQLite)

| テーブル | 役割 |
|---|---|
| `cards` | 監視カードマスタ(watchlist.csv の取込先) |
| `listings_ebay_sold` | eBay 落札履歴(相場の元データ。`listing_url + sold_at` で重複排除) |
| `listings_mercari` | メルカリ出品(今回の実行で見えなかった出品は `active=0` = 売切れ扱い) |
| `listings_snkrdunk` | スニダン商品(価格は最安出品価格) |
| `matches` | 相場×仕入候補×損益の計算結果。**毎回全削除→再構築される** |
| `fx_rates` | USD/JPY レート履歴 |
| `ignore_list` | ダッシュボードで「無視」した出品(以後非表示・非通知) |
| `notified_deals` | Discord 通知済みの出品(再通知防止) |
| `scrape_runs` | スクレイプ実行ログ(クエリ数・失敗数・パース失敗数) |

### マッチング confidence

出品タイトルと watchlist カードの同一判定(`cardgap/matching/engine.py`)。

| confidence | 条件 |
|---|---|
| `high` | カード番号一致 + セット記号一致(watchlist にセット指定がある場合)+ PSA グレード条件一致。セット指定なしのカード(カードダス等)は番号一致で high |
| `medium` | カード番号一致 + PSA グレード条件一致(セット記号が片方に無く確認できない) |
| `low` | カード名のみ一致 + PSA グレード条件一致(番号がタイトルから取れない) |
| `none` | 不一致。番号・セット・グレードのどれかが**明示的に食い違う**場合も none(例: 同じ 201/190 でもセット違い、PSA9 出品を PSA10 カードに当てる等) |

PSA グレード条件: watchlist でグレード指定あり → タイトルのグレードが完全一致すること。
watchlist が生カード(グレード空欄)→ タイトルに PSA 表記が**無い**こと(PSA 品を raw 相場に
混ぜると価格が壊れるため厳格にしている)。

対象は**日本語版のみ**: タイトルに他言語であることが明示された出品
(`ENGLISH` / `英語版` / `Korean` 等)は番号が一致しても `none` で除外される
(英語版はコレクター番号が同一でも別相場のため)。eBay 検索クエリにも自動で
`Japanese` が付与される。

相場集計と Discord 通知には confidence が `high` / `medium` の落札データ・仕入候補のみ使われる。

同一出品が複数の watchlist カード(例: 同じカードの raw 行と PSA10 行)のクエリ結果に
現れた場合は、**confidence の高い判定が優先**して出品に紐づく(処理順に依存しない)。

### 損益計算式(`cardgap/profit.py` と同一)

```
実効レート        = USD/JPY × (1 - conversion_margin)
想定売上JPY       = eBay売却中央値USD × 実効レート
eBay手数料JPY     = 想定売上 × (FVF + international_fee + promoted)
                    + per_order_fee_usd × 実効レート
仕入総額JPY       = 仕入価格 × (1 + 仕入手数料率) + 仕入送料
実質利益JPY       = 想定売上 - eBay手数料 - 発送送料 - 仕入総額
利益率            = 実質利益 ÷ 仕入総額
```

### 相場信頼度

eBay 直近 `ebay_lookback_days`(既定 30)日の落札件数が `threshold.min_sold_count_30d`(既定 3)
未満なら `reliability=low`。low の案件はダッシュボードには出せるが **Discord 通知はされない**
(たまたま 1 件高く売れただけの「相場」で仕入れるのを防ぐ)。

## 制約・既知のリスク

- **eBay の bot 検知**: 検索結果が 0 件になったり CAPTCHA ページが返ることがある
  (ログに `no items parsed` が出る)。その場合はクエリ数(watchlist の有効カード数や
  `max_ebay_queries_per_day`)を減らす、数日置いてから再開する。
- **eBay の日次クエリ上限**: `max_ebay_queries_per_day` は `scrape_runs` の実績で管理され、
  **同日に複数回実行しても合計で上限を超えない**。watchlist が上限より多い場合は
  実行ごとに続きのカードから順繰りに巡回する(毎回同じ先頭 50 枚に偏らない)。
- **メルカリの商品状態・出品日時は取得しない**: 検索一覧ページには表示されないため
  `condition` / `listed_at` は常に NULL。商品詳細ページを 1 件ずつ開けば取れるが、
  リクエスト数が出品数分に膨らみ低頻度アクセスの前提が崩れるため MVP では意図的に
  取得しない(必要になったら要検討)。
- **メルカリの部分失敗と在庫失効**: 「今回見えなかった出品は売切れ扱い(`active=0`)」の
  処理は、クエリが失敗したカードの出品を対象外にする(取得失敗＝売切れではない)。
  全クエリ失敗時は失効処理自体をスキップする。
- **スニダン(2026-08 時点)**: キーワード検索がログイン必須になったため収集を停止中
  (`categories.pokemon.snkrdunk: false`)。ログインが必要なページはスコープ外。仕様が
  戻ったら true に切り替える
- **eBay(2026-08 時点)**: GitHub Actions の IP には「Security Measure」ページ(bot検知)が
  返り収集不可。サーキットブレーカーで数分で切り上げる設計。対応方針は Issue/会話で相談
- **メルカリの海外IP表示**: 海外IPからは価格が US$ 表示になるが、aria-label の円価格を
  読むため収集は正常に動く
- **メルカリ / スニダンの DOM 変更**: パーサが壊れたら `config.yaml` の `scrape.debug_html_dir` に
  ディレクトリを指定して取得 HTML を保存し、実際の HTML を見ながら
  `cardgap/scrape/{mercari,snkrdunk,ebay}.py` のセレクタを修正 → `tests/fixtures/` の
  フィクスチャ HTML も更新してテストを通す。
- **スニダン購入手数料**: `buy_side.snkrdunk_buyer_fee_rate`(既定 5.5%)は要実額確認。
  実際の購入画面の手数料と違ったら config.yaml を直す。
- **ナルト系の流動性**: eBay での落札件数が少なく、`min_sold_count_30d` に届かず
  reliability=low になりやすい。閾値を下げる場合は相場の信頼性が落ちることを理解した上で。
- **為替 API のフォールバック**: API 失敗時は DB に保存済みの前回レート → それも無ければ
  `fx.fallback_rate`(既定 150.0)の順で落ちる。長期間 API が死んでいると古いレートで
  計算し続けるため、`fx_rates` テーブルの `fetched_at` をたまに確認する。

## テスト

ネットワーク・Playwright 起動なしで動く(パーサはフィクスチャ HTML でテスト)。

```bash
cd CardGap
python3 -m pytest            # 全テスト(pytest.ini で tests/ を対象に -q 実行)
python3 -m pytest tests/test_matching.py -q   # 個別実行の例
```

## プロジェクト構成

```
cardgap/
├── README.md
├── config.yaml               # 全設定(手数料率・閾値・ディレイ・エクスポート等)
├── requirements.txt
├── pytest.ini
├── .github/
│   └── workflows/
│       └── deploy-pages.yml  # site/ をビルドして GitHub Pages にデプロイ
├── scripts/
│   ├── daily.sh              # 日次バッチ + JSON push(cron から呼ぶ。Mac/Linux)
│   └── daily.ps1             # 同上(Windows タスクスケジューラ用)
├── cardgap/                  # Python パッケージ本体
│   ├── __main__.py           # メインCLI (initdb/fx/match/deals/notify/run/export/digest)
│   ├── config.py             # config.yaml ローダ
│   ├── models.py             # データ型と confidence 定数
│   ├── db.py                 # SQLite スキーマ + データアクセス層
│   ├── watchlist.py          # data/watchlist.csv の取込
│   ├── fx.py                 # USD/JPY レート取得
│   ├── stats.py              # eBay 相場集計(中央値・件数・信頼度)
│   ├── profit.py             # 損益計算
│   ├── notify.py             # Discord Webhook 通知 + 日次ダイジェスト
│   ├── export.py             # サイト用 JSON エクスポート(deals/history/summary)
│   ├── pipeline.py           # 日次バッチ本体(scripts/daily.sh から呼ばれる)
│   ├── matching/             # 同一カード判定
│   │   ├── engine.py         # confidence 判定ロジック
│   │   ├── extract.py        # 番号/セット記号/PSAグレード抽出
│   │   ├── names.py          # 日英対訳辞書
│   │   └── normalize.py      # タイトル正規化
│   └── scrape/               # スクレイパー
│       ├── __main__.py       # スクレイパー単体CLI
│       ├── browser.py        # Playwright 共通処理(ディレイ・リトライ・HTMLダンプ)
│       ├── ebay.py           # eBay Sold 検索
│       ├── mercari.py        # メルカリ検索
│       └── snkrdunk.py       # スニダン検索
├── site/                     # Webダッシュボード(React + Vite。GitHub Pages で公開)
│   └── public/data/          # 日次バッチが書き出す deals/history/summary.json
├── dashboard/
│   └── app.py                # Streamlit ダッシュボード(ローカル用)
├── data/
│   ├── watchlist.csv         # 監視カード一覧
│   ├── pokemon_names.csv     # ポケモン日英対訳辞書
│   └── naruto_names.csv      # ナルト日英対訳辞書
└── tests/                    # pytest(ネットワーク不要)
    └── fixtures/             # 各サイトの検索結果HTMLサンプル
```
