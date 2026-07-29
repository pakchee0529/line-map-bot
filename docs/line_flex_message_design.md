# LINE Flex Message and Map Preview Design

更新日: 2026-07-29

## 1. 目的

電柱・径間検索の採用結果を、通常テキストとURLだけでなく、
地図プレビュー、状態、若番・老番、補正理由、地図操作を含む
Flex Messageとして返す。

検索ロジックは表示方式から分離し、Flex生成または画像生成が失敗しても
従来テキストで必ず返信できる構造を維持する。

## 2. 実行系

- 公開Python実行系: `Procfile` -> `gunicorn app:app`
- Python検索コア: `search_core.py`
- Python LINE表示: `line_flex_builder.py`
- Pythonプレビュー画像: `map_preview.py`
- Node互換実装: `server.js`, `node_search_core.js`,
  `line_flex_builder.js`, `map_preview_service.js`
- 地図HTML: `templates/map.html`, `templates/multi_map.html`
- 地番図: `cadastral_service.py`, `node_cadastral_store.js`

公開URL `line-map-bot-ouvo.onrender.com` はPython版を実行している。
旧Python版にあった2点径間限定Flex処理は削除し、全検索種別を扱える
共通カード生成へ置き換えた。Node版にも同じ契約を実装し、将来の起動方式変更で
表示仕様が戻らないようにする。

## 3. 処理境界

```text
利用者入力
  -> search_core.py / node_search_core.js
  -> build_search_response() / buildSearchResponse()
  -> plainText + cards
  -> line_flex_builder.js
  -> LINE Flex Message
```

Pythonの `process_text_logic()` とNodeの `buildSearchReply()` は
互換用テキストAPIとして残す。

Flexが無効、カードがない、またはLINE送信でFlexが拒否された場合は
`plainText` を通常テキストメッセージとして送る。

## 4. カード種別

- 1点検索: 採用地点、Googleマップ、1点プレビュー
- 2点径間: 若番・老番、2点地図・地番図、老番側Googleマップ
- 冠称名検索: 登録電柱件数、冠称名マルチピン地図
- 半径200m: 該当件数、周辺地図
- 補正あり: 補正名と理由
- 片点のみ: 一部未解決の明示
- 未解決: 候補と候補再検索ボタン
- 複数行: 最大11件の結果カードと1件のまとめ地図カード

状態は色だけでなく、次のラベルを必ず表示する。

- 確認済み
- 補正あり
- 一部未解決
- 候補確認
- 周辺検索
- 冠称名検索
- まとめ

## 5. 地図プレビュー

`GET /api/map-preview?points=lat,lng|lat,lng...` が1024x512 PNGを返す。
Python本番系はPillow、Node互換系はSharpで生成する。

- OpenStreetMapタイルを表示範囲だけ取得して合成
- 確定した2点径間だけ、若番を1、老番を2としてピン内に表示して線で接続
- 冠称名、周辺200m、複数行は独立ピンとし、推測線を生成しない
- 五條市地番図の範囲内では境界、地番、引出線を重ねる
- OpenStreetMapおよび五條市地番図の帰属表示を画像内に付ける
- 同じ地点の完成画像をプロセス内で最大100件キャッシュ
- タイル取得失敗時も背景、ピン、線を含むPNGを生成

画像URLには座標だけを含め、利用者ID、LINEトークン、管理番号などは含めない。

## 6. 運用スイッチ

```text
LINE_FLEX_REPLY_ENABLED=true
MAP_PREVIEW_TILES_ENABLED=true
```

- `LINE_FLEX_REPLY_ENABLED=false`: 従来テキスト返信へ即時復帰
- `MAP_PREVIEW_TILES_ENABLED=false`: 外部タイルなしの簡易PNGへ切替

どちらも未設定時は有効。現在値は `/healthz/search` で秘密値なしに確認できる。

## 7. 安全条件

- FlexのURIと画像はHTTPSだけを採用する
- `altText` は常に従来テキストから作る
- Flexカルーセルは12バブルを超えない
- 画像はLINE上限内のPNGとし、通常は1MB未満を目標にする
- GPS正本、検索採用ロジック、地番図DBはこの表示変更では更新しない
- Flex生成失敗を検索失敗として扱わない

## 8. 回帰確認

- 1点、2点、冠称省略、未解決候補、複数行
- 12バブル上限
- HTTPS以外のアクション除外
- タイルなしPNG
- 地番図重畳PNG
- `/map`, `/multi-map`, `/api/map-preview`
- `/healthz/search` の表示スイッチ
