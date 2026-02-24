# macOS .app バンドル化 実装計画

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Kindle Page Captureをアイコンクリックで起動できるmacOS .appバンドルとしてビルドする

**Architecture:** プロジェクトルート内にビルドスクリプト (`scripts/build_app.sh`) を置き、`dist/KindleCapture.app` を生成する。.app内のlaunchスクリプトがプロジェクトの `venv/bin/python main.py` を直接呼び出すため、ソース変更が即反映される。

**Tech Stack:** Bash, macOS .app バンドル構造 (Info.plist), sips (PNG→icns変換)

**設計ドキュメント:** `docs/plans/2026-02-24-macos-app-bundle-design.md`

---

### Task 1: build_app.sh — launchスクリプト生成

**Files:**
- Create: `scripts/build_app.sh`

**Step 1: テスト用のシェルスクリプト検証スクリプトを書く**

`tests/test_build_app.sh` を作成。ビルドスクリプトを実行して、期待するファイル構造が生成されるか検証する。

```bash
#!/bin/bash
# tests/test_build_app.sh - build_app.sh の出力を検証するテスト
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$SCRIPT_DIR/dist"
APP_DIR="$DIST_DIR/KindleCapture.app"

# クリーンアップ
rm -rf "$DIST_DIR"

# ビルド実行
bash "$SCRIPT_DIR/scripts/build_app.sh"

PASS=0
FAIL=0

assert() {
    local description="$1"
    local condition="$2"
    if eval "$condition"; then
        echo "  PASS: $description"
        ((PASS++))
    else
        echo "  FAIL: $description"
        ((FAIL++))
    fi
}

echo "=== build_app.sh テスト ==="

# ディレクトリ構造
assert ".app ディレクトリが存在する" "[ -d '$APP_DIR/Contents' ]"
assert "MacOS ディレクトリが存在する" "[ -d '$APP_DIR/Contents/MacOS' ]"
assert "Resources ディレクトリが存在する" "[ -d '$APP_DIR/Contents/Resources' ]"

# ファイルの存在
assert "launch スクリプトが存在する" "[ -f '$APP_DIR/Contents/MacOS/launch' ]"
assert "launch スクリプトに実行権限がある" "[ -x '$APP_DIR/Contents/MacOS/launch' ]"
assert "Info.plist が存在する" "[ -f '$APP_DIR/Contents/Info.plist' ]"

# Info.plist の内容
assert "Info.plist に CFBundleName がある" "grep -q 'CFBundleName' '$APP_DIR/Contents/Info.plist'"
assert "Info.plist に CFBundleExecutable がある" "grep -q 'launch' '$APP_DIR/Contents/Info.plist'"
assert "Info.plist に CFBundleIdentifier がある" "grep -q 'com.local.kindle-capture' '$APP_DIR/Contents/Info.plist'"

# launch スクリプトの内容
assert "launch が venv/bin/python を参照している" "grep -q 'venv/bin/python' '$APP_DIR/Contents/MacOS/launch'"
assert "launch が main.py を参照している" "grep -q 'main.py' '$APP_DIR/Contents/MacOS/launch'"

# クリーンアップ
rm -rf "$DIST_DIR"

echo ""
echo "=== 結果: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] || exit 1
```

**Step 2: テストを実行して失敗を確認**

Run: `bash tests/test_build_app.sh`
Expected: FAIL（`scripts/build_app.sh` がまだ存在しないため）

**Step 3: build_app.sh を実装する**

```bash
#!/bin/bash
# scripts/build_app.sh - KindleCapture.app を生成するビルドスクリプト
set -euo pipefail

# プロジェクトルートを特定
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$PROJECT_DIR/dist"
APP_DIR="$DIST_DIR/KindleCapture.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

echo "=== KindleCapture.app をビルド中 ==="

# 1. venv が存在しなければ作成
if [ ! -d "$PROJECT_DIR/venv" ]; then
    echo "venv を作成中..."
    python3 -m venv "$PROJECT_DIR/venv"
    "$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
    echo "venv 作成完了"
fi

# 2. 既存の .app を削除して再作成
rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

# 3. launch スクリプトを生成
cat > "$MACOS_DIR/launch" << 'LAUNCH_EOF'
#!/bin/bash
# KindleCapture launcher
# .app/Contents/MacOS/launch → プロジェクトルートは3階層上
DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$DIR"
exec "$DIR/venv/bin/python" "$DIR/main.py"
LAUNCH_EOF
chmod +x "$MACOS_DIR/launch"

# 4. Info.plist を生成
cat > "$CONTENTS_DIR/Info.plist" << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>KindleCapture</string>
    <key>CFBundleDisplayName</key>
    <string>Kindle Page Capture</string>
    <key>CFBundleIdentifier</key>
    <string>com.local.kindle-capture</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleExecutable</key>
    <string>launch</string>
    <key>CFBundleIconFile</key>
    <string>app.icns</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
</dict>
</plist>
PLIST_EOF

# 5. アイコンをコピー
if [ -f "$PROJECT_DIR/resources/app.icns" ]; then
    cp "$PROJECT_DIR/resources/app.icns" "$RESOURCES_DIR/app.icns"
    echo "カスタムアイコンをコピーしました"
elif [ -f "$PROJECT_DIR/resources/app.png" ]; then
    # PNG → icns 変換 (macOS標準のsipsコマンドを使用)
    ICONSET_DIR=$(mktemp -d)/app.iconset
    mkdir -p "$ICONSET_DIR"
    for SIZE in 16 32 64 128 256 512; do
        sips -z $SIZE $SIZE "$PROJECT_DIR/resources/app.png" --out "$ICONSET_DIR/icon_${SIZE}x${SIZE}.png" > /dev/null 2>&1
    done
    for SIZE in 32 64 256 512 1024; do
        HALF=$((SIZE / 2))
        sips -z $SIZE $SIZE "$PROJECT_DIR/resources/app.png" --out "$ICONSET_DIR/icon_${HALF}x${HALF}@2x.png" > /dev/null 2>&1
    done
    iconutil -c icns "$ICONSET_DIR" -o "$RESOURCES_DIR/app.icns"
    echo "PNG からアイコンを変換しました"
else
    echo "注意: resources/app.icns または resources/app.png が見つかりません。デフォルトアイコンで起動します。"
fi

echo ""
echo "=== ビルド完了 ==="
echo "アプリ: $APP_DIR"
echo ""
echo "使い方:"
echo "  1. Finder で $APP_DIR を開く"
echo "  2. Dock にドラッグしてピン留め"
echo "  3. アイコンをクリックして起動"
```

**Step 4: テストを実行して成功を確認**

Run: `bash tests/test_build_app.sh`
Expected: 全テスト PASS

**Step 5: コミット**

```bash
git add scripts/build_app.sh tests/test_build_app.sh
git commit -m "feat: add build_app.sh to generate macOS .app bundle"
```

---

### Task 2: .gitignore に dist/ を追加

**Files:**
- Modify: `.gitignore`

**Step 1: .gitignore に dist/ を追記**

`.gitignore` の末尾に以下を追加:

```
dist/
```

**Step 2: コミット**

```bash
git add .gitignore
git commit -m "chore: add dist/ to .gitignore"
```

---

### Task 3: resources/ ディレクトリとアイコンのプレースホルダー

**Files:**
- Create: `resources/.gitkeep`

**Step 1: resources ディレクトリを作成**

```bash
mkdir -p resources
touch resources/.gitkeep
```

**Step 2: コミット**

```bash
git add resources/.gitkeep
git commit -m "chore: add resources/ directory for app icon"
```

---

### Task 4: README にアプリ化の手順を追記

**Files:**
- Modify: `README.md`

**Step 1: README を確認し、アプリ化セクションを追記**

README.md の適切な場所に以下を追加:

```markdown
## macOS アプリとして使う / Use as macOS App

### ビルド / Build

```bash
bash scripts/build_app.sh
```

### 起動 / Launch

1. `dist/KindleCapture.app` が生成されます
2. Finder で開いて Dock にドラッグしてピン留め
3. アイコンをクリックして起動

### カスタムアイコン / Custom Icon

- `resources/app.icns` または `resources/app.png` (1024x1024推奨) を配置してから `build_app.sh` を実行
- PNG は自動的に .icns に変換されます
```

**Step 2: コミット**

```bash
git add README.md
git commit -m "docs: add macOS app build instructions to README"
```

---

### Task 5: 手動動作確認

**Step 1: ビルドして起動テスト**

```bash
bash scripts/build_app.sh
open dist/KindleCapture.app
```

Expected: Kindle Page Capture のGUIウィンドウが表示される

**Step 2: ソース変更の即反映を確認**

`main.py` のウィンドウタイトル等を一時的に変更し、.app を再起動して変更が反映されることを確認。その後元に戻す。
