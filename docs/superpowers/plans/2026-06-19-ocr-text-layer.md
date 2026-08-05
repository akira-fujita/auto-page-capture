# OCR Text-Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed a searchable, invisible text layer into captured PDFs using macOS Vision OCR so NotebookLM can read the text directly instead of re-OCRing image-only PDFs.

**Architecture:** Add an `OcrEngine` (Vision-backed) that returns recognized text + normalized boxes per image. Extend `PdfGenerator.generate()` with an `ocr` flag: when on, build the PDF with reportlab (image drawn full-page + invisible text mode-3 overlaid at each box) instead of img2pdf. The engine is injectable so the PDF logic is unit-testable without Vision. A default-on checkbox in the export dialog drives the flag.

**Tech Stack:** Python 3.10+, PyQt6, Pillow, reportlab (new), pyobjc-framework-Vision (new), pypdf (test-side extraction), img2pdf (kept for OCR-off path).

## Global Constraints

- Platform: macOS only.
- Minimize dependencies; the two new ones (`reportlab`, `pyobjc-framework-Vision`) are pip-only, no system binaries. Installation requires explicit user confirmation before running pip.
- TDD for every feature step: write failing test → confirm fail → implement → confirm pass → commit.
- Never commit without the user's go-ahead in this flow; the plan groups commits per task.
- `ocr=False` must remain byte-for-byte the current img2pdf behavior (backward compatible).
- Coordinate convention: Vision `boundingBox` is normalized with bottom-left origin; reportlab canvas origin is also bottom-left — no Y-flip needed.

---

### Task 1: Add dependencies

**Files:**
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `reportlab` and `pyobjc-framework-Vision` available for import in later tasks.

- [ ] **Step 1: Add the two dependencies to requirements.txt**

Edit `requirements.txt` to add (place above the `# dev` block):

```
reportlab>=4.0.0
pyobjc-framework-Vision>=10.0
```

- [ ] **Step 2: Confirm with the user, then install**

Per project policy, ask the user to confirm installing new packages. After confirmation:

Run: `source venv/bin/activate && pip install "reportlab>=4.0.0" "pyobjc-framework-Vision>=10.0"`
Expected: both install without error.

- [ ] **Step 3: Verify imports work**

Run: `source venv/bin/activate && python -c "import reportlab; import Vision; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "build: add reportlab and pyobjc-framework-Vision for OCR text layer"
```

---

### Task 2: PdfGenerator OCR path (unit-testable, OS-independent)

**Files:**
- Modify: `src/export/pdf_generator.py`
- Create: `src/export/ocr_engine.py` (only the `TextBox` dataclass in this task)
- Test: `tests/test_pdf_generator.py`

**Interfaces:**
- Produces: `TextBox(text: str, x: float, y: float, w: float, h: float, confidence: float)` dataclass in `src/export/ocr_engine.py`. `x, y, w, h` are normalized 0..1, bottom-left origin.
- Produces: `PdfGenerator.generate(image_paths: list[Path], output_path: Path, ocr: bool = False, ocr_engine=None) -> None`. When `ocr=True` and `ocr_engine is None`, it lazily constructs `VisionOcrEngine()` (added in Task 3). An injected `ocr_engine` must expose `recognize(image_path: Path) -> list[TextBox]`.
- Consumes: `pypdf` (already a dependency) in tests for text extraction.

- [ ] **Step 1: Create the TextBox dataclass**

Create `src/export/ocr_engine.py`:

```python
# src/export/ocr_engine.py
"""OCRエンジン: 画像から文字とその位置を認識する"""

from dataclasses import dataclass


@dataclass
class TextBox:
    """認識された1テキスト片。座標は正規化(0..1)・左下原点。"""

    text: str
    x: float
    y: float
    w: float
    h: float
    confidence: float
```

- [ ] **Step 2: Write the failing test for OCR-on text embedding**

Add to `tests/test_pdf_generator.py`:

```python
from pypdf import PdfReader
from src.export.ocr_engine import TextBox


class FakeOcrEngine:
    """既知のテキストボックスを返すテスト用エンジン"""

    def __init__(self, boxes):
        self._boxes = boxes
        self.calls = []

    def recognize(self, image_path):
        self.calls.append(image_path)
        return self._boxes


def test_generate_with_ocr_embeds_extractable_text(saved_image_paths):
    """ocr=Trueのとき、埋め込んだテキストがpypdfで抽出できる"""
    engine = FakeOcrEngine([TextBox("テスト本文", 0.1, 0.1, 0.5, 0.1, 0.99)])
    gen = PdfGenerator()
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "ocr.pdf"
        gen.generate(saved_image_paths, output, ocr=True, ocr_engine=engine)
        assert output.exists()
        reader = PdfReader(str(output))
        assert len(reader.pages) == len(saved_image_paths)
        text = "".join(page.extract_text() for page in reader.pages)
        assert "テスト本文" in text
        assert len(engine.calls) == len(saved_image_paths)


def test_generate_without_ocr_has_no_text(saved_image_paths):
    """ocr=False(既定)のときはテキストが埋め込まれない(従来通り画像PDF)"""
    gen = PdfGenerator()
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "image_only.pdf"
        gen.generate(saved_image_paths, output)
        reader = PdfReader(str(output))
        text = "".join(page.extract_text() for page in reader.pages).strip()
        assert "テスト本文" not in text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `source venv/bin/activate && pytest tests/test_pdf_generator.py::test_generate_with_ocr_embeds_extractable_text -v`
Expected: FAIL (`generate()` got an unexpected keyword argument `ocr`).

- [ ] **Step 4: Implement the OCR path in PdfGenerator**

Replace the contents of `src/export/pdf_generator.py` with:

```python
# src/export/pdf_generator.py
"""PDF生成機能"""

from pathlib import Path
import img2pdf
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

_CJK_FONT = "HeiseiKakuGo-W5"
_font_registered = False


def _ensure_font():
    """日本語出力用CIDフォントを一度だけ登録"""
    global _font_registered
    if not _font_registered:
        pdfmetrics.registerFont(UnicodeCIDFont(_CJK_FONT))
        _font_registered = True


class PdfGenerator:
    """画像からPDFを生成するクラス"""

    def generate(
        self,
        image_paths: list[Path],
        output_path: Path,
        ocr: bool = False,
        ocr_engine=None,
    ) -> None:
        """画像リストからPDFを生成。

        ocr=Trueのとき、各ページに見えないテキストレイヤーを重ねた
        検索可能PDFを生成する。ocr=Falseのときは従来通りの画像PDF。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not ocr:
            paths_str = [str(p) for p in image_paths]
            with open(output_path, "wb") as f:
                f.write(img2pdf.convert(paths_str))
            return

        if ocr_engine is None:
            from src.export.ocr_engine import VisionOcrEngine
            ocr_engine = VisionOcrEngine()

        self._generate_with_ocr(image_paths, output_path, ocr_engine)

    def _generate_with_ocr(self, image_paths, output_path, ocr_engine) -> None:
        _ensure_font()
        c = canvas.Canvas(str(output_path))
        for image_path in image_paths:
            with Image.open(image_path) as im:
                width, height = im.size
            c.setPageSize((width, height))
            c.drawImage(str(image_path), 0, 0, width=width, height=height)

            for box in ocr_engine.recognize(image_path):
                x = box.x * width
                y = box.y * height
                font_size = max(box.h * height, 1.0)
                text_obj = c.beginText(x, y)
                text_obj.setFont(_CJK_FONT, font_size)
                text_obj.setTextRenderMode(3)  # 不可視(見た目は画像のまま)
                text_obj.textOut(box.text)
                c.drawText(text_obj)

            c.showPage()
        c.save()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source venv/bin/activate && pytest tests/test_pdf_generator.py -v`
Expected: all PASS (including the two pre-existing tests).

- [ ] **Step 6: Commit**

```bash
git add src/export/pdf_generator.py src/export/ocr_engine.py tests/test_pdf_generator.py
git commit -m "feat: add OCR text-layer path to PdfGenerator with injectable engine"
```

---

### Task 3: VisionOcrEngine (macOS Vision integration)

**Files:**
- Modify: `src/export/ocr_engine.py`
- Test: `tests/test_ocr_engine.py`

**Interfaces:**
- Consumes: `TextBox` from Task 2.
- Produces: `VisionOcrEngine.recognize(image_path: Path) -> list[TextBox]` — the default engine `PdfGenerator` constructs when `ocr=True` and no engine is injected.

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_ocr_engine.py`:

```python
# tests/test_ocr_engine.py
import tempfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from src.export.ocr_engine import TextBox

vision = pytest.importorskip("Vision", reason="macOS Vision framework not available")
from src.export.ocr_engine import VisionOcrEngine


def _make_text_image(path: Path, text: str):
    img = Image.new("RGB", (600, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 70), text, fill="black")
    img.save(path, "PNG")


def test_recognizes_latin_text():
    engine = VisionOcrEngine()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "hello.png"
        _make_text_image(path, "HELLO123")
        boxes = engine.recognize(path)
        assert all(isinstance(b, TextBox) for b in boxes)
        joined = "".join(b.text for b in boxes).upper().replace(" ", "")
        assert "HELLO123" in joined
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source venv/bin/activate && pytest tests/test_ocr_engine.py -v`
Expected: FAIL (`cannot import name 'VisionOcrEngine'`). On a machine without Vision the test is skipped instead — that is acceptable, but development happens on macOS where it should run and fail.

- [ ] **Step 3: Implement VisionOcrEngine**

Append to `src/export/ocr_engine.py`:

```python
from pathlib import Path


class VisionOcrEngine:
    """macOS Vision を用いたOCRエンジン"""

    def recognize(self, image_path: Path) -> list["TextBox"]:
        import Vision
        from Foundation import NSURL

        url = NSURL.fileURLWithPath_(str(image_path))
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(["ja-JP", "en-US"])
        request.setUsesLanguageCorrection_(True)

        success, _error = handler.performRequests_error_([request], None)
        if not success:
            return []

        boxes: list[TextBox] = []
        for observation in (request.results() or []):
            candidates = observation.topCandidates_(1)
            if candidates is None or len(candidates) == 0:
                continue
            top = candidates[0]
            bbox = observation.boundingBox()
            boxes.append(
                TextBox(
                    text=top.string(),
                    x=float(bbox.origin.x),
                    y=float(bbox.origin.y),
                    w=float(bbox.size.width),
                    h=float(bbox.size.height),
                    confidence=float(top.confidence()),
                )
            )
        return boxes
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source venv/bin/activate && pytest tests/test_ocr_engine.py -v`
Expected: PASS on macOS. If `top.confidence()` or `boundingBox()` accessor names differ in the installed pyobjc-framework-Vision, adjust the accessor and re-run until green — the test is the source of truth.

- [ ] **Step 5: Commit**

```bash
git add src/export/ocr_engine.py tests/test_ocr_engine.py
git commit -m "feat: add VisionOcrEngine backed by macOS Vision"
```

---

### Task 4: Export dialog checkbox

**Files:**
- Modify: `src/ui/chapter_dialog.py:217-223` (add checkbox), `src/ui/chapter_dialog.py:374-401` (pass flag)
- Test: `tests/test_main_window.py` or new `tests/test_chapter_dialog.py`

**Interfaces:**
- Consumes: `PdfGenerator.generate(..., ocr=bool)` from Task 2.
- Produces: `ChapterDialog.ocr_check` (QCheckBox, default checked); `_export_pdfs()` passes `ocr=self.ocr_check.isChecked()` to both `generate()` calls.

- [ ] **Step 1: Write the failing test**

Create `tests/test_chapter_dialog.py` (uses a fake generator to assert the flag is forwarded; no real Qt event loop needed because we call `_export_pdfs` directly after constructing the dialog under `QApplication`):

```python
# tests/test_chapter_dialog.py
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image
from PyQt6.QtWidgets import QApplication

from src.ui.chapter_dialog import ChapterDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def image_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = []
        for i in range(2):
            p = Path(tmpdir) / f"page_{i}.png"
            Image.new("RGB", (50, 50), "white").save(p, "PNG")
            paths.append(p)
        yield paths


def test_ocr_checkbox_default_on_and_forwarded(qapp, image_paths, monkeypatch):
    with tempfile.TemporaryDirectory() as outdir:
        dialog = ChapterDialog(image_paths, Path(outdir), keep_images=True)
        assert dialog.ocr_check.isChecked() is True

        calls = []
        monkeypatch.setattr(
            dialog.pdf_generator,
            "generate",
            lambda paths, out, ocr=False, ocr_engine=None: calls.append(ocr),
        )
        dialog.merge_check.setChecked(True)
        dialog.chapter_pdf_check.setChecked(False)
        # 通知/メッセージボックスを抑止
        monkeypatch.setattr("src.ui.chapter_dialog.QMessageBox.information", lambda *a, **k: None)
        monkeypatch.setattr("src.utils.notification.send_notification", lambda *a, **k: None)

        dialog._export_pdfs()
        assert calls == [True]
```

Note: adjust the `ChapterDialog(...)` constructor call to match its actual signature in `src/ui/chapter_dialog.py` (around line 110-120) before running.

- [ ] **Step 2: Run the test to verify it fails**

Run: `source venv/bin/activate && pytest tests/test_chapter_dialog.py -v`
Expected: FAIL (`'ChapterDialog' object has no attribute 'ocr_check'`).

- [ ] **Step 3: Add the checkbox**

In `src/ui/chapter_dialog.py`, after the `chapter_pdf_check` block (currently ending at line 223), add:

```python
        self.ocr_check = QCheckBox("テキストを埋め込む (OCR)")
        self.ocr_check.setChecked(True)
        output_layout.addWidget(self.ocr_check)
```

- [ ] **Step 4: Forward the flag in `_export_pdfs`**

In `_export_pdfs()`, read the flag once near the top of the `try` block:

```python
            ocr = self.ocr_check.isChecked()
```

Then update both calls:

```python
                self.pdf_generator.generate(self.image_paths, merged_path, ocr=ocr)
```

```python
                    self.pdf_generator.generate(chapter_images, pdf_path, ocr=ocr)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `source venv/bin/activate && pytest tests/test_chapter_dialog.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `source venv/bin/activate && pytest -v`
Expected: all PASS (Vision integration test passes or skips).

- [ ] **Step 7: Commit**

```bash
git add src/ui/chapter_dialog.py tests/test_chapter_dialog.py
git commit -m "feat: add default-on OCR checkbox to export dialog"
```

---

### Task 5: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: behavior delivered in Tasks 1-4.

- [ ] **Step 1: Update README features and dependencies**

In `README.md`:
- Add a feature bullet under 機能/Features:
  `- **テキスト埋め込み (OCR)** / **Embedded text (OCR)** — macOS Visionで認識したテキストレイヤーをPDFに重ねる（NotebookLMの精度向上） / Overlays a Vision-recognized text layer onto the PDF (improves NotebookLM accuracy)`
- Add to the dependencies table:
  - `reportlab | テキストレイヤー付きPDF生成 / Text-layered PDF generation`
  - `pyobjc-framework-Vision | macOS OCR / macOS OCR`
- In Basic steps, note that step 5 (PDF出力) has a default-on "テキストを埋め込む (OCR)" option.

- [ ] **Step 2: Verify no other doc references conflict**

Run: `grep -rn "img2pdf\|OCR\|テキスト" README.md docs/ | grep -v specs/ | grep -v plans/`
Expected: README reflects the OCR option; no contradictory statements remain.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document OCR text-layer option and new dependencies"
```

---

## Self-Review

- **Spec coverage:** Vision engine (Task 3), reportlab text-layer + injectable engine + backward-compatible OCR-off (Task 2), two new deps (Task 1), default-on checkbox applied to both merge/chapter exports (Task 4), README consistency (Task 5), tests both unit and macOS-integration (Tasks 2-4). Out-of-scope items (pdf_splitter OCR, progress bar) remain excluded. All spec sections map to a task.
- **Placeholder scan:** No TBD/TODO; all code steps contain full code. The two "adjust to actual signature/accessor" notes are concrete instructions, not deferred work.
- **Type consistency:** `TextBox(text, x, y, w, h, confidence)` defined in Task 2 and constructed identically in Task 3. `generate(image_paths, output_path, ocr=False, ocr_engine=None)` consistent across Tasks 2 and 4. `recognize(image_path) -> list[TextBox]` consistent across the fake (Task 2) and Vision (Task 3) engines.
