# 公開 Node 検索・地番図反映

## 背景

- 公開先 `line-map-bot.onrender.com` は、リポジトリ内の Python `app.py` ではなく `package.json` の `node server.js` で起動していた。
- Python 側へ追加した検索 v2 と地番図 API は公開プロセスから参照されず、公開先の `/healthz/search` も 404 だった。
- 旧 `server.js` の検索処理には未定義関数が残り、LINE 検索時に例外で返信できない状態だった。

## 対応

- PC 版の正規化方針を Node 用 `node_search_core.js` に移植した。
- 全角・半角、空白、範囲記号、後半省略、枝番、G9 補完、近傍候補を共通検索結果に統合した。
- LINE 返信、単点地図、2点地図、冠称名一括地図を同じ検索結果から生成するよう `server.js` を再構成した。
- `node:sqlite` を使う `node_cadastral_store.js` を追加し、圧縮済み地番図 DB の展開、ヘルスチェック、bbox API を公開 Node プロセスへ接続した。
- `/healthz/search`、`/healthz/search/sample`、`/healthz/cadastral` を追加した。
- Render の Node バージョンを `>=22.5` とし、依存関係を `pnpm-lock.yaml` で固定した。

## 検証

- `node --test tests-node/*.test.js`: 6件成功
- `木ノ原40E1S3～木ノ原40E1S4`: 2点を解決
- `木ノ原40E1S3～S4`: 後半省略を補完して2点を解決
- 冠称名 `木ノ原`: 複数電柱を取得
- Node の公開2点地図ルート: HTML 200、地番図操作を含む
- 地番図実データ: bbox/zoom 18 で198要素、範囲内、未切り詰め

## 運用上の確認先

- `/healthz/search`: 公開検索エンジン、Gitリビジョン、GPS件数・ハッシュ
- `/healthz/search/sample`: 固定サンプルの2点解決
- `/healthz/cadastral`: 地番図レイヤーとデータセット状態
- `/api/cadastral/features`: 地番図 GeoJSON
