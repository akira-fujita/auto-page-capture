# OCRテキストレイヤー埋め込み 設計

- 日付: 2026-06-19
- 対象: Kindle Page Capture（macOS専用）
- 目的: スクリーンショット由来の画像PDFに、検索可能な透明テキストレイヤーを埋め込み、NotebookLMでの要約・引用・検索精度を安定させる。

## 背景・課題

現状は `スクリーンショット画像 → img2pdf → PDF`（`src/export/pdf_generator.py`）で、出来上がるPDFは**画像のみ・テキストレイヤーなし**。NotebookLMは画像PDFを取り込むと内部でOCRするが精度が不安定で、特に日本語（縦書き・ルビ・フォント依存）で誤認識が増える。こちらで検証済みのテキストレイヤーを埋め込んでおけば、NotebookLMはOCRをやり直さずそのテキストを使うため精度が安定する。

## 方針決定（ブレストの結論）

- OCRエンジン: **macOS Vision**（`pyobjc-framework-Vision`）を採用。理由: 本プロジェクトはmacOS専用かつ「依存は最小限」が方針、`.app`配布との相性、入力がKindleの鮮明な描画画像のためVisionの精度で十分。OCRmyPDF（Tesseract+Ghostscript）はシステムバイナリ導入が重く、本ツールの性格に合わないため不採用。
- 対象書籍: 横書き・縦書き両方。縦書きはVisionの自動判定をフォールバックとして利用。
- UX: PDF出力オプションに「テキストを埋め込む (OCR)」チェックボックスを追加、**既定ON**。

## アーキテクチャ

```
画像 ──┬─ (OCR OFF) ─→ img2pdf ───────────────→ 画像PDF（従来通り）
       └─ (OCR ON)  ─→ OcrEngine(Vision)
                        → 各ページ: 画像 + 透明テキスト
                        → reportlab で重ねて出力 → 検索可能PDF
```

設計原則: 画像は見た目用にそのまま配置し、その上に「見えない（PDFテキスト描画モード3）テキスト」を文字位置へ重ねる。**見た目は従来と完全に同一**。OCR結果が本文の見た目を改変することはない。PDFビューアやNotebookLMはテキストを抽出できる。

### 新規モジュール `src/export/ocr_engine.py`

- `TextBox`: データ構造。`text: str`、正規化座標 `x, y, w, h`（0..1, 原点はVision準拠で左下）、`confidence: float`。
- `VisionOcrEngine.recognize(image_path: Path) -> list[TextBox]`:
  - `VNImageRequestHandler` + `VNRecognizeTextRequest` を使用。
  - 設定: `recognitionLevel = accurate`、`recognitionLanguages = ["ja-JP", "en-US"]`、`usesLanguageCorrection = True`。
  - 縦書きはVisionが自動判定。各 `VNRecognizedTextObservation` から最有力候補のテキストと `boundingBox` を取得。
- インターフェースは「`recognize(image_path) -> list[TextBox]`」のみ。これにより `PdfGenerator` から差し替え可能。

### `PdfGenerator` の拡張（`src/export/pdf_generator.py`）

- シグネチャ: `generate(image_paths, output_path, ocr: bool = False, ocr_engine=None)`。
- `ocr=False`: 現行の img2pdf パスを維持（**後方互換**）。
- `ocr=True`:
  - `ocr_engine` が `None` の場合は `VisionOcrEngine()` を生成（実行時の既定）。テスト時はフェイクを注入。
  - reportlab の `canvas` で、各画像について:
    1. ページサイズを画像のピクセルサイズに設定。
    2. 画像をページ全面に描画。
    3. 各 `TextBox` を画像座標へ変換し、`setFillAlpha(0)` 相当ではなく **テキストレンダリングモード3（不可視）** で文字を描画。フォントは日本語が出力できるCID フォント（reportlabの `HeiseiMin-W3` / `HeiseiKakuGo-W5` などのCJK標準フォント）を使用。
  - 出力PDFは見た目は画像PDFと同一で、テキスト抽出が可能。

### UI（`src/ui/chapter_dialog.py`）

- 出力オプション群（`merge_check` / `chapter_pdf_check` の近傍）に **「テキストを埋め込む (OCR)」チェックボックス（既定 checked）** を追加。
- `_export_pdfs()` で `ocr = self.ocr_check.isChecked()` を取得し、`merge`・章ごと両方の `generate(..., ocr=ocr)` に渡す。
- OCRはページごとに走るため、ページ数が多いとき体感が伸びる。最小限としてOCR実行中はカーソルをビジー表示にする（プログレスバーは将来拡張、YAGNI）。

## 依存ライブラリの追加

いずれも pip 完結・システムバイナリ不要。

| 追加 | 用途 |
|---|---|
| `pyobjc-framework-Vision` | Apple Vision OCR（既存のpyobjc系の一員） |
| `reportlab` | 画像＋透明テキスト層のPDF生成 |

`requirements.txt` に追記する。

## テスト方針（TDD）

- **`PdfGenerator`（ユニット, OS非依存）**
  - フェイクOCRエンジン（既知の `TextBox` を返す）を注入し、生成PDFを `pypdf` で開いて検証:
    - 期待テキストが抽出できる。
    - ページ数が画像枚数と一致する。
    - ページサイズが画像ピクセルサイズに対応する。
  - `ocr=False` のとき従来通り img2pdf 画像PDF（テキスト抽出は空）になることを検証。
- **`VisionOcrEngine`（統合, macOS限定）**
  - 既知文字列を描いた画像（Pillowで生成）を Vision にかけ、その文字列を含む結果が返ることを検証。
  - Vision が利用できない環境では `pytest.skip`。

## 非対象（YAGNI）

- 既存PDF分割機能（`pdf_splitter`）へのOCR適用は対象外。今回は「キャプチャ→PDF出力」経路に限定。
- プログレスバーUI、OCR言語のユーザー設定、信頼度しきい値の調整UIは将来拡張。
