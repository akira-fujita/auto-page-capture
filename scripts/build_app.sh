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
# .app/Contents/MacOS/launch → プロジェクトルートは4階層上
# dist/KindleCapture.app/Contents/MacOS/launch
DIR="$(cd "$(dirname "$0")/../../../.." && pwd)"
if [ ! -f "$DIR/main.py" ]; then
    osascript -e 'display dialog "KindleCapture.app はプロジェクトフォルダ内の dist/ に配置してください。" buttons {"OK"} default button "OK" with icon stop'
    exit 1
fi
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
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
PLIST_EOF

# 5. アイコンをコピー
if [ -f "$PROJECT_DIR/resources/app.icns" ]; then
    cp "$PROJECT_DIR/resources/app.icns" "$RESOURCES_DIR/app.icns"
    echo "カスタムアイコンをコピーしました"
elif [ -f "$PROJECT_DIR/resources/app.png" ]; then
    # PNG → icns 変換 (macOS標準のsipsコマンドを使用)
    TMPDIR_ICON=$(mktemp -d)
    ICONSET_DIR="$TMPDIR_ICON/app.iconset"
    mkdir -p "$ICONSET_DIR"
    for SIZE in 16 32 64 128 256 512; do
        sips -z $SIZE $SIZE "$PROJECT_DIR/resources/app.png" --out "$ICONSET_DIR/icon_${SIZE}x${SIZE}.png" > /dev/null 2>&1
    done
    for SIZE in 32 64 256 512 1024; do
        HALF=$((SIZE / 2))
        sips -z $SIZE $SIZE "$PROJECT_DIR/resources/app.png" --out "$ICONSET_DIR/icon_${HALF}x${HALF}@2x.png" > /dev/null 2>&1
    done
    iconutil -c icns "$ICONSET_DIR" -o "$RESOURCES_DIR/app.icns"
    rm -rf "$TMPDIR_ICON"
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
