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
        ((PASS++)) || true
    else
        echo "  FAIL: $description"
        ((FAIL++)) || true
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
assert "launch が4階層上を参照している" "grep -q '\.\./\.\./\.\./\.\.' '$APP_DIR/Contents/MacOS/launch'"

# クリーンアップ
rm -rf "$DIST_DIR"

echo ""
echo "=== 結果: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] || exit 1
