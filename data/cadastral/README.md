# 地番参考図データ

このディレクトリには、五條市オープンデータから生成した読取専用 SQLite を配置します。

既定ファイル名:

`gojo_chiban.sqlite`

SQLite 本体は大きいため Git にはコミットしません。生成方法は次のとおりです。

```powershell
python tools\build_gojo_cadastral_db.py `
  --output data\cadastral\gojo_chiban.sqlite
```

変換時だけ、以下の依存パッケージが必要です。

```powershell
python -m pip install -r tools\requirements-cadastral-build.txt
```

本番アプリの実行時依存には `pyproj`、`pyshp`、GDAL を追加しません。

生成後の検証:

```powershell
python tools\verify_cadastral_db.py
```

本番ビルドで、GitHub Release等に置いた検証済みSQLiteを取得する場合:

```powershell
python tools\fetch_cadastral_dataset.py `
  --url "https://配布先/gojo_chiban.sqlite" `
  --sha256 "事前確認したSHA-256"
```

環境変数でも `CADASTRAL_DATA_URL`、`CADASTRAL_DATA_SHA256`、
`CADASTRAL_DATA_PATH` を指定できます。

アプリ側は次のフラグを設定した場合だけ地番レイヤーを有効にします。

```text
CADASTRAL_LAYER_ENABLED=1
```

`0` または未設定なら、地番APIと地番ボタンは無効になり、従来の地図表示に戻ります。

地番参考図は土地の正確な位置、筆界、形状、権利関係を証するものではありません。
利用時は五條市の最新のオープンデータ利用規約を確認してください。
