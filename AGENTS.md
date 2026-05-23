# AGENTS.md — line-map-bot エージェント共通ルールブック

> **このファイルを最初に読む。** 作業開始前に本ファイルを確認し、禁止事項を守る。  
> **ippatsu-pc** は母艦/管理寄り、**line-map-bot** は現場即応（LINE 即検索）寄り。横断ルールは ippatsu-pc `AGENTS.md` も参照。

---

## §0. Repo position

| 項目 | 内容 |
|------|------|
| **名称** | LINE Bot「座標いっぱつちゃん」（電柱ナビ） |
| **役割** | 電柱名・径間名・座標入力に対し、Google Maps URL / 自前 map・multi-pin map を返す **現場即検索** ツール |
| **スタック** | **本番:** Python `app.py`（Flask + line-bot-sdk + gunicorn、`Procfile`）／**併存:** Node `server.js`（Express + `@line/bot-sdk`） |
| **地図 UI** | `templates/map.html`（単点）、`templates/multi_map.html`（複数ピン） |
| **状態** | Redis / Valkey（`REDIS_URL`）— multi-map セッション・利用者/会社設定・招待コード等 |
| **正本データ** | `GPS.json`・`coords.json`（位置データ。ユーザー明示指示なしに変更禁止） |
| **デプロイ** | Render。**`main` push → 自動デプロイの可能性が高い**（人間承認必須） |
| **設定ファイル** | `render.yaml` は **なし**（Render ダッシュボード + `Procfile` + `requirements.txt`） |

**作業開始前（必須）:**

```
git status -sb
git log --oneline -5
```

- 追跡ファイルに意図しない変更がある場合は、勝手に stash / reset せず人間に報告して停止する。

---

## §1. Roles

| エージェント | 主な担当 | 備考 |
|---|---|---|
| **ChatGPT** | 方針整理・設計判断・Cursor 用ミッション作成 | 長期状態の正本は AGENTS.md / `docs/work_logs/` |
| **Cursor Agents Window** | 調査・編集・検証・branch commit / push | **`main` merge / `origin/main` push は人間 Go 後のみ** |
| **Cursor Editor / Chat** | diff 確認・局所修正・質問応答 | 大きな実装・commit は Agents Window へ |
| **Claude Cowork** | 横断調査・docs / AGENTS 整合レビュー | コード実装・push はしない |
| **人間（りょーまさん）** | `main` merge・deploy・Render 設定・secret・本番判断 | 不可逆操作は必ず人間が実施 |

---

## §2. File zones

### 🟢 Safe-ish（docs 中心）

- `AGENTS.md`（本ファイル）
- `docs/*`・`docs/work_logs/*`（作業ログは §6）
- `README.txt` 等の README 類

### 🟡 Caution（変更は差分を小さく・影響範囲を明示）

| パス | 備考 |
|------|------|
| **`app.py`** | 本番エントリ（`Procfile`: `gunicorn app:app`）。LINE webhook・検索・map URL・Redis 連携 |
| **`server.js`** | Node 版ロジック（`GPS.json` 読込）。本番が Python 主体でも挙動差分に注意 |
| **`templates/*`** | 地図 HTML（`/map`・`/multi-map`） |
| **`requirements.txt`** | Python 依存。変更はリグレッションリスク |
| **`package.json`** | Node 依存（`npm start` → `server.js`）。`package-lock.json` がある場合も同様 |
| **`Procfile`** | Render 起動コマンド。変更は **deploy 挙動に直結** |

### 🔴 Protected

| 対象 | 扱い |
|------|------|
| **`GPS.json`** / **`coords.json`** | 位置データの正本。**ユーザー明示指示なしに変更・上書き禁止**（読取のみ可） |
| **`.env` / `.env.*`** | 作成・変更・表示・commit 禁止 |
| **LINE / Redis credentials** | `LINE_CHANNEL_ACCESS_TOKEN`・`LINE_CHANNEL_SECRET`・`BASE_URL`・`REDIS_URL` 等の **実値**は表示・commit 禁止 |
| **Render 設定** | ダッシュボード上の環境変数・サービス設定。AI から変更しない |

### 🔴 絶対に commit しない

- secret / token / key の **実値**
- 意図しない `GPS.json` / `coords.json` の差分

---

## §3. Git / deploy rules

- **`main` への push** は Render 本番反映の可能性があるため **人間承認必須**
- **`main` merge** も人間 Go 後のみ
- 作業は **`cursor/*` ブランチ**で行い、branch push は可（レビュー用）
- **`force push` 禁止**
- **`git add .` 禁止** — 対象パスを明示して add
- deploy 確認・Render 設定変更は **人間承認**
- commit 前に `GPS.json` / `coords.json` がステージに乗っていないか必ず確認

---

## §4. Secret rules

以下の **実値**を表示・commit・ソースへの直書き **禁止**:

- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_CHANNEL_SECRET`
- `BASE_URL`（公開 URL そのものの記載は設計メモ程度に留め、token 類と混同しない）
- `REDIS_URL`（および Valkey / Redis 接続文字列）
- その他 token / key / secret

- **`.env` を AI が作成・変更・表示しない**
- 確認・更新は **LINE Developers**・**Render ダッシュボード**で人間が実施

---

## §5. Data rules

- **`GPS.json` / `coords.json`** はユーザー明示指示なしに変更しない
- 正規化・検索ロジック・候補展開を変える場合は、**検索結果・地図 URL への影響**を報告する
- 既存の **多ピン地図**（`/multi-map`）・**位置情報返信**・**2点 span 地図**を壊さない
- `server.js` と `app.py` でロジックが二重化している箇所がある。片方だけ直すと挙動がずれる可能性がある

---

## §6. Work logs

- 作業ログは **この repo 内の `docs/work_logs/`** に新規作成する
- **1作業 = 1ログファイル**。既存ログへの追記は禁止
- ログは変更ファイルと **同一 commit** に含める
- **複数 repo 横断作業のみ** `ippatsu-pc/docs/work_logs/` に横断まとめログを追加してよい（repo-local ログの代替ではない）

### 命名規則

```
docs/work_logs/YYYY-MM-DD_HHMM_<agent>_<task-slug>.md
```

例: `docs/work_logs/2026-05-23_2013_cursor_add-agents-md.md`

### テンプレート（抜粋）

```markdown
# 作業ログ: <タスク名>

| 項目 | 値 |
|------|----|
| Date | YYYY-MM-DD HH:MM |
| Repo | line-map-bot |
| Branch | cursor/xxx |
| Agent | cursor / cowork / human |

## Purpose / Changes / Files changed
## Checks performed
## Things not done（main merge, deploy, secrets, data 等）
```

- **`main` merge / deploy / secret / 位置データ変更**は人間承認

---

## §7. Completion report

作業完了時は **§6 の作業ログ** を作成し、報告に以下を含める。

1. 作業ブランチ  
2. 変更ファイル  
3. 作業ログファイル（`docs/work_logs/` のパス）  
4. 実行した確認  
5. commit ID  
6. push 結果  
7. **`main` / `origin/main` を変更していないこと**  
8. **Render deploy していないこと**  
9. **secret を表示 / commit していないこと**  
10. 最終 `git status`  
11. **main merge 可否の判断**（docs-only か、本番コード・データ・secret に触れていないか）

---

## 参照

| ファイル | 内容 |
|----------|------|
| `README.txt` | セットアップ・入力仕様・Render 環境変数名 |
| `Procfile` | `web: gunicorn app:app` |
| `package.json` | `npm start` → `node server.js` |
| `requirements.txt` | Flask / line-bot-sdk / gunicorn / redis |
| **ippatsu-pc** `AGENTS.md` | 母艦の secret 禁止・横断作業ログ方針 |
