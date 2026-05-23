# 作業ログ: line-map-bot AGENTS.md と作業ログ運用の整備

| 項目 | 値 |
|------|----|
| Date | 2026-05-23 20:13 |
| Repo | line-map-bot |
| Branch | cursor/add-agents-md |
| Agent | cursor |

## Purpose

- LINE Bot「座標いっぱつちゃん」のエージェント向け `AGENTS.md` を repo 実態に合わせて整備する
- repo-local `docs/work_logs/` 運用（1作業1ファイル）を明文化する
- `main` merge / Render deploy は行わず、専用ブランチへ push まで

## Changes

- `AGENTS.md` を新規追加（§0〜§7: 役割・ゾーン・deploy/secret/data・作業ログ・完了報告）
- 本ファイルを `docs/work_logs/` に新規作成

## Files changed

- `AGENTS.md`
- `docs/work_logs/2026-05-23_2013_cursor_add-agents-md.md`

## Repo survey (read-only)

| 項目 | 確認結果 |
|------|----------|
| `server.js` | あり（Express + LINE SDK、`GPS.json` 読込） |
| `app.py` | あり（Flask、本番 `Procfile` → gunicorn） |
| `requirements.txt` | あり |
| `package.json` | あり（`start`: `node server.js`） |
| `package-lock.json` | リポジトリ内になし |
| `templates/` | `map.html`, `multi_map.html` |
| `GPS.json` / `coords.json` | あり（未変更） |
| `render.yaml` | なし |
| `Procfile` | `web: gunicorn app:app` |
| Redis | `app.py` で `REDIS_URL`（multi-map・設定・招待等） |

## Checks performed

- `git status -sb`（追跡ファイルの意図しない変更なし）
- `main` = `origin/main` = `d1521c7`
- `git diff --name-status` / `--stat`（AGENTS.md + 作業ログのみ）
- secret 実値の表示・commit なし

## Things not done

- main merge: **not done**
- `origin/main` push: **not done**
- Render deploy: **not done**
- secret 表示: **not done**
- `GPS.json` / `coords.json` 変更: **not done**
- `server.js` / `app.py` / 依存ファイル変更: **not done**

## Commit

（commit 後に SHA を記載）

## Push

（push 後に結果を記載）

## Next action

- 人間: 本レポートの merge 可否判断後、`cursor/add-agents-md` → `main` の merge + `origin/main` push（Render 自動デプロイの有無を Render 側で確認）
