使い方
1. GitHubに server.js / package.json / GPS.json をアップロード
2. Renderで Web Service を作成
3. Environment Variables を設定
   LINE_CHANNEL_ACCESS_TOKEN=...
   LINE_CHANNEL_SECRET=...
   BASE_URL=https://あなたのアプリ.onrender.com
4. LINE Developers の Webhook URL を
   https://あなたのアプリ.onrender.com/webhook
   に設定

入力仕様
- 1行だけで「緯度,経度」のとき: 周辺200mの電柱地図URLを返します
- それ以外: 径間名として処理します
- 複数行入力可。空行は無視します

径間名の返信形式
径間名
URL
（必要なときだけ但し書き）
