# Kindle Page Capture

Kindleアプリのページを自動キャプチャしてPDFに変換するmacOSデスクトップツール。

A macOS desktop tool that automatically captures Kindle app pages and converts them to PDF.

## 機能 / Features

- **ウィンドウ自動検出** / **Auto window detection** — Kindleウィンドウを自動で検出・選択 / Automatically detects and selects Kindle windows
- **自動ページ送り** / **Auto page turning** — 指定ページ数を自動でキャプチャ / Captures the specified number of pages automatically
- **キャプチャ設定** / **Capture settings** — キャプチャ間隔・ページ送り方向を調整可能 / Adjustable capture interval and page direction
- **カスタム領域選択** / **Custom region selection** — ドラッグで任意のキャプチャ領域を指定（マルチモニター対応） / Drag to select any screen region (multi-monitor support)
- **章分割** / **Chapter splitting** — サムネイル一覧から章の区切りを設定（NotebookLMでの要約に便利） / Set chapter boundaries from thumbnail preview (useful for summarization with NotebookLM)
- **PDF出力** / **PDF export** — 全ページ結合 or 章ごとに分割してPDF出力 / Export as a single merged PDF or split by chapter
- **デスクトップ通知** / **Desktop notifications** — キャプチャ完了・PDF出力完了時にmacOS通知 / Notifies on capture and export completion

## 必要環境 / Requirements

- macOS
- Python 3.10+
- スクリーン録画権限 / Screen recording permission（システム設定 > プライバシーとセキュリティ > 画面収録 / System Settings > Privacy & Security > Screen Recording）

## インストール / Installation

```bash
git clone <repository-url>
cd auto-page-capture
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 依存ライブラリ / Dependencies

| パッケージ / Package | 用途 / Purpose |
|---|---|
| PyQt6 | GUI |
| pyautogui | スクリーンショット・キー送信 / Screenshot & key input |
| Pillow | 画像処理 / Image processing |
| img2pdf | PDF生成 / PDF generation |
| pyobjc-framework-Quartz | macOSウィンドウ管理 / macOS window management |
| pyobjc-framework-Cocoa | macOSアプリ制御 / macOS app control |

## 使い方 / Usage

```bash
source venv/bin/activate
python main.py
```

### 基本的な手順 / Basic steps

1. **ウィンドウ選択** / **Select window** — Kindleアプリを開いた状態で起動すると自動選択される / Launch with Kindle open and it auto-selects
2. **キャプチャ設定** / **Configure** — ページ数・送り方向（左/右）・キャプチャ間隔を設定 / Set page count, direction (left/right), and interval
3. **キャプチャ開始** / **Start capture** — 「キャプチャ開始」をクリック / Click the start button
4. **章分割（任意）** / **Split chapters (optional)** — キャプチャ完了後、サムネイルをクリックして章を区切る / After capture, click thumbnails to mark chapter boundaries
5. **PDF出力** / **Export PDF** — 全ページ結合 or 章ごとのPDFを出力 / Export as merged or per-chapter PDFs

### 注意事項 / Notes

- キャプチャ中は対象ウィンドウを動かさないでください / Do not move the target window during capture
- 他のウィンドウを前面に出さないでください / Do not bring other windows to the foreground

## プロジェクト構成 / Project Structure

```
auto-page-capture/
├── main.py                          # エントリーポイント / Entry point
├── src/
│   ├── capture/
│   │   ├── window_manager.py        # macOSウィンドウ管理 / Window management
│   │   ├── screenshot.py            # スクリーンショット / Screenshot capture
│   │   └── page_navigator.py        # ページ送り / Page navigation
│   ├── export/
│   │   ├── file_manager.py          # ファイル管理 / File management
│   │   └── pdf_generator.py         # PDF生成 / PDF generation
│   ├── ui/
│   │   ├── main_window.py           # メインウィンドウ / Main window
│   │   ├── chapter_dialog.py        # 章分割ダイアログ / Chapter splitting dialog
│   │   └── region_selector.py       # 領域選択オーバーレイ / Region selection overlay
│   └── utils/
│       └── notification.py          # デスクトップ通知 / Desktop notifications
└── tests/                           # テスト / Tests
```

## テスト / Tests

```bash
pytest
```

## ライセンス / License

MIT
