# 作業ログ: 公開 LINE Bot 検索・地番図更新

| 項目 | 値 |
|------|----|
| Date | 2026-07-29 14:26 |
| Repo | line-map-bot |
| Branch | main |
| Agent | Codex |

## Purpose

公開中の LINE Bot で `木ノ原40E1S3～40E1S4` が期待どおり応答せず、
ローカルだけでなく公開版を更新するようユーザーから明示指示を受けた。

## Changes

- PC 版の純粋な検索コアを LINE Bot 向けに分離して導入
- 若番・老番の独立解決、G9 補正、K/G9 警告、候補と理由を追加
- 冠称名のみの検索で同一冠称の登録電柱を一覧地図化
- `/healthz/search` に検索版、公開 revision、GPS 件数・SHA を追加
- 五條市地番参考図の SQLite を gzip で同梱し、起動時に展開
- 2 点地図に地番図 ON/OFF と安全なフォールバックを追加
- 地番図 API、SQLite read-only サービス、生成・取得・検証ツールを追加

## Checks performed

- `python -m py_compile app.py search_core.py search_normalize.py cadastral_service.py`
- `python -m unittest discover -s tests -v`: 16 tests OK
- `python tools/verify_cadastral_db.py`: verify_ok
- 空の一時配置先へ gzip を展開し、DB available / feature enabled を確認
- `木ノ原40E1S3～40E1S4` の 2 点 URL を確認
- `GPS.json` は PC 版と SHA-256・件数が一致
- `git diff --check`

## Safety

- `GPS.json` / `coords.json` は変更していない
- `.env` と secret は変更・表示・commit していない
- 既存の未追跡 `.claude/` は対象外
- 地番図表示失敗時も通常の 2 点地図を維持する
- 公開版更新は、この会話でのユーザー明示指示に基づく
