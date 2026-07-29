# 作業ログ: LINE Flex Messageと地図プレビュー

| 項目 | 値 |
|------|----|
| Date | 2026-07-29 15:22 |
| Repo | line-map-bot |
| Branch | codex/line-flex-map-preview-20260729 |
| Agent | codex |

## Purpose

公開Python版LINE Botの通常テキスト返信を、画像付きFlex Messageへ拡張する。
検索ロジックを変更せず、Flexまたは画像処理の失敗時は従来テキストへ退避する。
Node版にも同じ契約を実装し、将来の実行方式変更に備える。

## Changes

- 検索結果を `plainText + cards` として構造化
- 1点、2点、冠称名、周辺200m、未解決、複数行のFlexカードを追加
- 1024x512の地図プレビューPNG生成を追加
- OpenStreetMap、2点ピン・線、五條市地番図を画像へ合成
- 線は確定2点径間だけに限定し、冠称名・周辺・複数行では推測線を生成しない
- Flexと地図タイルを環境変数で個別に無効化可能にした
- health情報へ有効状態を追加
- 2点径間限定だった旧Python Flex処理を共通カード処理へ置換
- Flex上限、HTTPS制約、PNG、地番図、検索返信、HTTPルートをテスト

## Files changed

- `app.py`
- `line_flex_builder.py`
- `map_preview.py`
- `requirements.txt`
- `server.js`
- `line_flex_builder.js`
- `map_preview_service.js`
- `package.json`
- `pnpm-lock.yaml`
- `tests-node/server.test.js`
- `tests-node/line_flex_builder.test.js`
- `tests-node/map_preview_service.test.js`
- `tests/test_line_flex_builder.py`
- `tests/test_map_preview.py`
- `tests/test_python_flex_routes.py`
- `docs/line_flex_message_design.md`
- `docs/work_logs/2026-07-29_1522_codex_line-flex-map-preview.md`

## Checks performed

- Node syntax check: `server.js`, `line_flex_builder.js`, `map_preview_service.js`
- Node tests: 16 passed
- Python tests: 25 passed
- 実GPSによる木ノ原40E1S3～40E1S4プレビューを両実装で生成
- 地番図265 featureを含むPNGを目視確認
- Python本番系出力画像: 1024x512、約121KB
- Node互換系出力画像: 1024x512、約264KB
- 公開環境事前確認: Python `pc-core-v2`, revision `28dbf9e781e3`

## Things not done

- `main` mergeなし
- `origin/main` pushなし
- Render deployなし
- secret、`.env`、Render設定の変更なし
- `GPS.json`、`coords.json`、地番図DBの変更なし
- 既存の未追跡 `.claude/` には未接触
