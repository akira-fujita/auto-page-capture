# Kindle Page Capture

KindleアプリのページをMac上で自動キャプチャし、PDFとして出力するGUIアプリケーション。

## 機能

- macOSのウィンドウ一覧から対象アプリを選択
- 指定ページ数を自動でキャプチャ
- キャプチャ間隔・ページ送り方向を調整可能
- 章ごとにPDFを分割出力（NotebookLMでの要約に便利）
- 全体を1つのPDFにまとめることも可能

## 必要環境

- macOS
- Python 3.10+

## インストール

```bash
git clone <repository-url>
cd auto-page-capture
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 使い方

```bash
source venv/bin/activate
python main.py
```

1. 対象ウィンドウでKindleを選択
2. ページ数、ページ送り方向、キャプチャ間隔を設定
3. 「キャプチャ開始」をクリック
4. キャプチャ完了後、章分割画面でPDFを出力

## 注意事項

- キャプチャ中は対象ウィンドウを動かさないでください
- macOSのスクリーン録画権限が必要です（システム環境設定 > セキュリティとプライバシー > スクリーン収録）

## ライセンス

MIT
