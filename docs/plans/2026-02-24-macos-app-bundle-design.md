# macOS .app バンドル化 設計ドキュメント

**日付:** 2026-02-24
**目的:** Kindle Page Captureをアイコンクリックで起動できるmacOSアプリにする

## 要件

- 自分用（配布不要）
- ターミナル操作不要でアイコンクリック起動
- Dockにピン留め可能
- カスタムアイコン対応
- ソースコード変更が即反映（リビルド不要）

## アプローチ

手動 .app バンドル方式を採用。追加の依存パッケージなし、Git管理しやすく、ソース即反映。

### ファイル構造

```
プロジェクトルート/
├── scripts/
│   └── build_app.sh            # .app を生成するビルドスクリプト
├── resources/
│   └── app.icns                # カスタムアイコン（ユーザーが用意、またはPNGから変換）
├── dist/                       # .gitignore対象
│   └── KindleCapture.app/
│       └── Contents/
│           ├── Info.plist
│           ├── MacOS/
│           │   └── launch      # venv/bin/python main.py を実行するシェルスクリプト
│           └── Resources/
│               └── app.icns
```

### launch スクリプト

- 自身の位置からプロジェクトルートのパスを逆算
- `venv/bin/python main.py` を直接呼び出し（source activate 不要）
- 作業ディレクトリをプロジェクトルートに設定

### Info.plist

- `CFBundleName`: KindleCapture
- `CFBundleIdentifier`: com.local.kindle-capture
- `CFBundleIconFile`: app.icns
- `CFBundleExecutable`: launch
- `LSUIElement`: false（Dockに表示）

### build_app.sh

1. `dist/KindleCapture.app` のフォルダ構造を作成
2. `launch` スクリプトを生成して実行権限付与
3. `Info.plist` を生成
4. `resources/app.icns` があればコピー、なければデフォルト
5. venvが存在しなければ作成 + `pip install -r requirements.txt`
6. PNG→icns変換ヘルパー対応

### 使い方

1. 初回: `bash scripts/build_app.sh`
2. 生成された .app をDockにドラッグしてピン留め
3. 以降はアイコンクリックで起動
4. ソースを変更すれば即反映

### .gitignore

`dist/` を追加
