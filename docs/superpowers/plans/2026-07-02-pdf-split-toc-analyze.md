# 既存PDF分割への目次自動解析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 既存PDF分割ダイアログ (`PdfSplitDialog`) に「目次から章を自動解析」を追加し、TOCページを画像化 → `claude` CLI で章名+印刷ページ抽出 → アンカー補正で章行を自動生成する。

**Architecture:** 既存の `toc_analyzer`(`ClaudeTocEngine` / `compute_offset` / `entries_to_chapters`)を無改修で再利用。新規は (1) `PdfSplitter.render_page_image`(高解像度PNG保存)、(2) PDF専用の `PdfTocAnalyzeDialog`、(3) `PdfSplitDialog` への組込。既存 `TocAnalyzeDialog` は汎用化しない(回帰リスク回避 / Codex 指摘)。

**Tech Stack:** PyQt6, macOS Quartz(既存依存), pypdf, reportlab(テスト用PDF生成), `subprocess`。新規 pip 依存なし。

## Global Constraints

- Python 3.10+; 新規 pip 依存なし; UI 文言は日本語; `ui → export` 依存方向のみ。
- `ChapterRange` は 0始まり・end包含。`_ChapterRow` の開始ページ QSpinBox は 1始まり → 書き戻しは `start + 1`。
- アンカーUIは「印刷 p.X = PDF #Y ページ」と明示。`compute_offset(Y, X)` を使う。
- 目次ページ範囲は**両端 inclusive**。選択枚数を表示。
- 一時PNGは1回の解析run単位で `tempfile.TemporaryDirectory` に置き、成功/キャンセル/例外の全経路で破棄。
- プレビューは除外/重複統合/警告を明示し、確定は破壊的(既存行を置換)である旨を表示。
- TDD、コミットはタスク単位。

---

### Task 1: PdfSplitter.render_page_image(高解像度PNG保存)

**Files:**
- Modify: `src/export/pdf_splitter.py`
- Test: `tests/test_pdf_splitter.py`(追記。無ければ作成)

**Interfaces:**
- Produces: `PdfSplitter.render_page_image(pdf_path: Path, page_index: int, output_path: Path, max_height: int = 2000) -> Path`
  - 既存 `render_page_thumbnail` と同じ Quartz 経路で、`max_height` を解像度ノブとして高解像度レンダリングし、`output_path`(PNG)に保存してそのパスを返す。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pdf_splitter.py
import tempfile
from pathlib import Path

import pytest

Quartz = pytest.importorskip("Quartz", reason="macOS Quartz not available")

from PyQt6.QtWidgets import QApplication
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from src.export.pdf_splitter import PdfSplitter


@pytest.fixture(scope="module")
def qapp():
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def _make_pdf(path: Path, pages: int = 3):
    c = canvas.Canvas(str(path), pagesize=letter)
    for i in range(pages):
        c.drawString(72, 720, f"Page {i + 1}")
        c.showPage()
    c.save()


def test_render_page_image_writes_readable_png(qapp):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pdf = tmp / "sample.pdf"
        _make_pdf(pdf, pages=3)
        out = tmp / "toc.png"
        splitter = PdfSplitter()
        result = splitter.render_page_image(pdf, page_index=1, output_path=out, max_height=1600)
        assert result == out
        assert out.exists()
        # 高解像度で保存されている(サムネイルより十分大きい)
        from PIL import Image
        with Image.open(out) as img:
            assert img.height >= 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pdf_splitter.py -v` → FAIL(AttributeError: render_page_image)

- [ ] **Step 3: Implement**

`src/export/pdf_splitter.py` に追加(既存 `render_page_thumbnail` のロジックを流用し、QPixmap を PNG 保存):

```python
    def render_page_image(
        self, pdf_path: Path, page_index: int, output_path: Path, max_height: int = 2000
    ) -> Path:
        """PDFページを高解像度PNGとして保存し、そのパスを返す。

        max_height は OCR 品質を左右する解像度ノブ。
        """
        pixmap = self.render_page_thumbnail(pdf_path, page_index, max_height=max_height)
        if not pixmap.save(str(output_path), "PNG"):
            raise RuntimeError(f"PDFページ画像の保存に失敗しました: {output_path}")
        return output_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pdf_splitter.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/export/pdf_splitter.py tests/test_pdf_splitter.py
git commit -m "feat: add PdfSplitter.render_page_image (high-res PNG for OCR)"
```

---

### Task 2: PdfTocAnalyzeDialog(PDF専用の目次解析ダイアログ)

**Files:**
- Create: `src/ui/pdf_toc_analyze_dialog.py`
- Test: `tests/test_pdf_toc_analyze_dialog.py`

**Interfaces:**
- Consumes: `ClaudeTocEngine`, `compute_offset`, `entries_to_chapters`, `ChapterRange`(既存 `src/export/toc_analyzer.py`)、`PdfSplitter`(Task 1)。
- Produces:
  - `PdfTocAnalyzeDialog(pdf_path: Path, page_count: int, engine=None, splitter=None, parent=None)`
  - `dialog.result_ranges: list[ChapterRange]`(0始まり、確定後に参照)、`dialog.warnings: list[str]`
  - 内部: `_run_analyze()`(選択TOCページ→高解像度PNG(temp)→engine.analyze→`_entries` 格納→`_recompute`)、`_recompute()`(offset反映→result_ranges/警告更新→プレビュー描画。前付けオプション適用)
  - UI要素(テスト依存): `toc_start_spin`/`toc_end_spin`(1始まり inclusive)、`anchor_printed_spin`/`anchor_pdf_spin`、`preface_check`(「前付けを別章として残す」非デフォルト)、`analyze_btn`、`apply_btn`、プレビュー `table`、`warning_label`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pdf_toc_analyze_dialog.py
import sys
import tempfile
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from src.export.toc_analyzer import TocEntry, ChapterRange
from src.ui.pdf_toc_analyze_dialog import PdfTocAnalyzeDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class _FakeEngine:
    def __init__(self, entries):
        self._entries = entries
        self.called_with = None

    def analyze(self, image_paths):
        self.called_with = list(image_paths)
        return self._entries


class _FakeSplitter:
    def __init__(self):
        self.rendered = []

    def render_page_image(self, pdf_path, page_index, output_path, max_height=2000):
        self.rendered.append(page_index)
        Path(output_path).write_bytes(b"PNG")  # ダミー
        return Path(output_path)


def _dialog(entries, page_count=188):
    engine = _FakeEngine(entries)
    splitter = _FakeSplitter()
    d = PdfTocAnalyzeDialog(Path("/tmp/book.pdf"), page_count, engine=engine, splitter=splitter)
    return d, engine, splitter


def test_inclusive_range_renders_correct_pages(qapp):
    d, engine, splitter = _dialog([TocEntry("第1章", 1)])
    d.toc_start_spin.setValue(3)
    d.toc_end_spin.setValue(5)  # inclusive: PDFページ 3,4,5 → index 2,3,4
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(11)
    d._run_analyze()
    assert splitter.rendered == [2, 3, 4]
    # engine には3枚の画像が渡る
    assert len(engine.called_with) == 3


def test_anchor_offset_maps_to_zero_based_start(qapp):
    d, engine, splitter = _dialog([TocEntry("第1章", 1), TocEntry("第2章", 45)])
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(11)  # offset = 11 - 1 = 10
    d._run_analyze()
    # 第1章: start = 1 + 10 - 1 = 10, 第2章: start = 45 + 10 - 1 = 54
    assert [ (c.name, c.start) for c in d.result_ranges ] == [("第1章", 10), ("第2章", 54)]


def test_out_of_range_entry_is_warned(qapp):
    d, engine, splitter = _dialog([TocEntry("第1章", 1), TocEntry("付録", 900)], page_count=188)
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(11)
    d._run_analyze()
    assert [c.name for c in d.result_ranges] == ["第1章"]
    assert len(d.warnings) == 1


def test_preface_option_prepends_front_matter(qapp):
    d, engine, splitter = _dialog([TocEntry("第1章", 1)], page_count=188)
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(11)  # 第1章 start = 10 → 前付け 0..9 が存在
    d.preface_check.setChecked(True)
    d._run_analyze()
    assert d.result_ranges[0].name == "前付け"
    assert d.result_ranges[0].start == 0
    assert d.result_ranges[0].end == 9
    assert d.result_ranges[1].name == "第1章"


def test_analyze_failure_resets_state(qapp, monkeypatch):
    class _Boom:
        def analyze(self, paths):
            raise RuntimeError("boom")
    splitter = _FakeSplitter()
    d = PdfTocAnalyzeDialog(Path("/tmp/b.pdf"), 188, engine=_Boom(), splitter=splitter)
    monkeypatch.setattr(
        "src.ui.pdf_toc_analyze_dialog.QMessageBox.critical", lambda *a, **k: None
    )
    d._run_analyze()
    assert d.result_ranges == []
    assert d.apply_btn.isEnabled() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pdf_toc_analyze_dialog.py -v` → FAIL(ModuleNotFoundError)

- [ ] **Step 3: Implement**

```python
# src/ui/pdf_toc_analyze_dialog.py
"""既存PDFの目次を解析して章範囲を提案するダイアログ"""

import tempfile
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QCheckBox,
    QPushButton, QGroupBox, QTableWidget, QTableWidgetItem,
    QMessageBox, QApplication,
)
from PyQt6.QtCore import Qt

from src.export.toc_analyzer import (
    ClaudeTocEngine, ChapterRange, compute_offset, entries_to_chapters,
)
from src.export.pdf_splitter import PdfSplitter


class PdfTocAnalyzeDialog(QDialog):
    """既存PDFの目次から章を自動解析するダイアログ"""

    def __init__(self, pdf_path: Path, page_count: int, engine=None, splitter=None, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.page_count = page_count
        self.engine = engine or ClaudeTocEngine()
        self.splitter = splitter or PdfSplitter()
        self._entries = []
        self.result_ranges = []
        self.warnings = []
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("目次から章を自動解析")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        n = self.page_count

        # ① 目次ページ範囲(inclusive)
        toc_group = QGroupBox("① 目次のPDFページ範囲(両端を含む)")
        toc_layout = QHBoxLayout(toc_group)
        self.toc_start_spin = QSpinBox(); self.toc_start_spin.setRange(1, max(1, n)); self.toc_start_spin.setPrefix("p.")
        self.toc_end_spin = QSpinBox(); self.toc_end_spin.setRange(1, max(1, n)); self.toc_end_spin.setPrefix("p.")
        self.toc_end_spin.setValue(min(2, n))
        self.toc_count_label = QLabel()
        toc_layout.addWidget(self.toc_start_spin); toc_layout.addWidget(QLabel("〜"))
        toc_layout.addWidget(self.toc_end_spin); toc_layout.addWidget(self.toc_count_label)
        toc_layout.addStretch()
        layout.addWidget(toc_group)

        # ② アンカー
        anchor_group = QGroupBox("② ページ番号アンカー(ズレ補正)")
        anchor_outer = QVBoxLayout(anchor_group)
        anchor_row = QHBoxLayout()
        self.anchor_printed_spin = QSpinBox(); self.anchor_printed_spin.setRange(1, 99999); self.anchor_printed_spin.setPrefix("印刷 p.")
        self.anchor_pdf_spin = QSpinBox(); self.anchor_pdf_spin.setRange(1, max(1, n)); self.anchor_pdf_spin.setPrefix("PDF #")
        anchor_row.addWidget(self.anchor_printed_spin); anchor_row.addWidget(QLabel("="))
        anchor_row.addWidget(self.anchor_pdf_spin); anchor_row.addStretch()
        anchor_outer.addLayout(anchor_row)
        self.anchor_example = QLabel(); self.anchor_example.setStyleSheet("color:#666;")
        anchor_outer.addWidget(self.anchor_example)
        layout.addWidget(anchor_group)

        self.preface_check = QCheckBox("最初の章より前のページを「前付け」として別章に残す")
        layout.addWidget(self.preface_check)

        self.analyze_btn = QPushButton("解析する")
        self.analyze_btn.clicked.connect(self._run_analyze)
        layout.addWidget(self.analyze_btn)

        self.summary_label = QLabel(); layout.addWidget(self.summary_label)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["章名", "→ PDFページ範囲"])
        layout.addWidget(self.table)
        self.warning_label = QLabel(); self.warning_label.setStyleSheet("color:#d32f2f;"); self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)

        btns = QHBoxLayout(); btns.addStretch()
        cancel = QPushButton("キャンセル"); cancel.clicked.connect(self.reject); btns.addWidget(cancel)
        self.apply_btn = QPushButton("この内容で章を設定(既存の行は置換されます)")
        self.apply_btn.clicked.connect(self.accept); self.apply_btn.setEnabled(False); btns.addWidget(self.apply_btn)
        layout.addLayout(btns)

        # ライブ更新
        self.toc_start_spin.valueChanged.connect(self._update_labels)
        self.toc_end_spin.valueChanged.connect(self._update_labels)
        self.anchor_printed_spin.valueChanged.connect(self._on_anchor_changed)
        self.anchor_pdf_spin.valueChanged.connect(self._on_anchor_changed)
        self._update_labels()

    def _update_labels(self):
        start, end = self.toc_start_spin.value(), self.toc_end_spin.value()
        count = max(0, end - start + 1)
        self.toc_count_label.setText(f"（{count}ページを解析）")
        offset = compute_offset(self.anchor_pdf_spin.value(), self.anchor_printed_spin.value())
        self.anchor_example.setText(
            f"例: 印刷 p.{self.anchor_printed_spin.value()} は PDF の {self.anchor_pdf_spin.value()} ページ目 "
            f"(ズレ offset={offset:+d})"
        )

    def _on_anchor_changed(self, _v):
        self._update_labels()
        if self._entries:
            self._recompute()

    def _selected_page_indices(self) -> list[int]:
        start = self.toc_start_spin.value()
        end = max(self.toc_end_spin.value(), start)
        return [p - 1 for p in range(start, end + 1)]  # 0始まりindex, inclusive

    def _run_analyze(self):
        indices = self._selected_page_indices()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                paths = []
                for idx in indices:
                    out = Path(tmp) / f"toc_{idx}.png"
                    self.splitter.render_page_image(self.pdf_path, idx, out)
                    paths.append(out)
                self._entries = self.engine.analyze(paths)
        except FileNotFoundError:
            self._reset_state()
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "エラー", "claude CLI が見つかりませんでした。手動でページを入力してください。")
            return
        except Exception as e:
            self._reset_state()
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "エラー", f"目次の解析に失敗しました:\n{e}\n\n手動でページを入力してください。")
            return
        QApplication.restoreOverrideCursor()
        self._recompute()

    def _reset_state(self):
        self._entries = []
        self.result_ranges = []
        self.warnings = []
        self._refresh_table()
        self.apply_btn.setEnabled(False)

    def _recompute(self):
        offset = compute_offset(self.anchor_pdf_spin.value(), self.anchor_printed_spin.value())
        ranges, warnings = entries_to_chapters(self._entries, offset, self.page_count)
        # 前付けオプション
        if self.preface_check.isChecked() and ranges and ranges[0].start > 0:
            ranges = [ChapterRange("前付け", 0, ranges[0].start - 1)] + ranges
        self.result_ranges = ranges
        self.warnings = warnings
        self._refresh_table()
        self.apply_btn.setEnabled(bool(ranges))

    def _refresh_table(self):
        self.table.setRowCount(len(self.result_ranges))
        for i, c in enumerate(self.result_ranges):
            self.table.setItem(i, 0, QTableWidgetItem(c.name))
            self.table.setItem(i, 1, QTableWidgetItem(f"p.{c.start + 1}-{c.end + 1}"))
        detected = len(self._entries)
        kept = len(self.result_ranges)
        self.summary_label.setText(
            f"目次から {detected} 件検出 → {kept} 章を作成。確定すると既存の章一覧は置き換えられます。"
        )
        self.warning_label.setText("\n".join(self.warnings))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pdf_toc_analyze_dialog.py -v` → PASS(5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ui/pdf_toc_analyze_dialog.py tests/test_pdf_toc_analyze_dialog.py
git commit -m "feat: add PdfTocAnalyzeDialog (PDF-specific TOC analysis)"
```

---

### Task 3: PdfSplitDialog への組込(ボタン＋行置換)

**Files:**
- Modify: `src/ui/pdf_split_dialog.py`
- Test: `tests/test_pdf_split_dialog.py`(追記。無ければ作成)

**Interfaces:**
- Consumes: `PdfTocAnalyzeDialog`(Task 2), `ChapterRange`
- Produces: `PdfSplitDialog._apply_toc_ranges(ranges: list[ChapterRange]) -> None`（既存 `_ChapterRow` を全消去し、各 range について `name` と `start_page = start + 1`（1始まり）で行を再生成、range更新）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pdf_split_dialog.py
import sys
import tempfile
from pathlib import Path

import pytest

Quartz = pytest.importorskip("Quartz", reason="macOS Quartz not available")
from PyQt6.QtWidgets import QApplication
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from src.export.toc_analyzer import ChapterRange
from src.ui.pdf_split_dialog import PdfSplitDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def pdf_path():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "book.pdf"
        c = canvas.Canvas(str(p), pagesize=letter)
        for i in range(10):
            c.drawString(72, 720, f"Page {i+1}"); c.showPage()
        c.save()
        yield p


def test_apply_toc_ranges_replaces_rows(qapp, pdf_path):
    dialog = PdfSplitDialog(pdf_path)
    ranges = [
        ChapterRange("前付け", 0, 4),   # start 0 → 開始 p.1
        ChapterRange("第1章", 5, 9),    # start 5 → 開始 p.6
    ]
    dialog._apply_toc_ranges(ranges)
    assert len(dialog._chapter_rows) == 2
    assert dialog._chapter_rows[0].name_edit.text() == "前付け"
    assert dialog._chapter_rows[0].start_spin.value() == 1
    assert dialog._chapter_rows[1].name_edit.text() == "第1章"
    assert dialog._chapter_rows[1].start_spin.value() == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pdf_split_dialog.py -v` → FAIL(AttributeError: _apply_toc_ranges)

- [ ] **Step 3: Implement**

`src/ui/pdf_split_dialog.py` の import に追加:

```python
from src.export.toc_analyzer import ChapterRange
```

`_init_ui` の説明文 `info` の直後にボタン追加:

```python
        toc_btn = QPushButton("目次から章を自動解析")
        toc_btn.clicked.connect(self._open_toc_analyze)
        layout.addWidget(toc_btn)
```

メソッド追加(`_build_chapters` の前あたり):

```python
    def _open_toc_analyze(self):
        """目次解析ダイアログを開き、確定したら章行を置換"""
        from src.ui.pdf_toc_analyze_dialog import PdfTocAnalyzeDialog
        dialog = PdfTocAnalyzeDialog(self.pdf_path, self.page_count, parent=self)
        if dialog.exec() and dialog.result_ranges:
            self._apply_toc_ranges(dialog.result_ranges)

    def _apply_toc_ranges(self, ranges: list[ChapterRange]):
        """解析結果で章行を全置換する（start は0始まり→1始まりの開始ページへ）"""
        # 既存行を全消去
        for row in list(self._chapter_rows):
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._chapter_rows.clear()
        # 新規行を生成
        for r in ranges:
            self._add_chapter_row(r.name, r.start + 1)
        self._update_ranges()
```

> `_add_chapter_row` は末尾で `self._chapter_rows[0].delete_btn.setEnabled(False)` を呼ぶため、最低1行あれば先頭行の削除ボタンは自動的に無効化される。`ranges` が空のケースは `_open_toc_analyze` 側の `and dialog.result_ranges` で弾かれる。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pdf_split_dialog.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/ui/pdf_split_dialog.py tests/test_pdf_split_dialog.py
git commit -m "feat: wire TOC auto-analyze into PdfSplitDialog"
```

---

### Task 4: ドキュメント更新・全テスト・手動確認

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README の「既存PDF分割」機能に追記**

`## 機能 / Features` の既存PDF分割の項目に、目次自動解析が既存PDFでも使える旨を1行追記する:

```markdown
  - 目次ページを指定すれば `claude` CLI が章名・ページ番号を読み取り、章の開始ページを自動入力（キャプチャ／既存PDFの両フローに対応） / Point at the TOC pages and the `claude` CLI auto-fills chapter start pages (works in both the capture and existing-PDF flows)
```

- [ ] **Step 2: 全テスト**

Run: `pytest -v`
Expected: 全 PASS(Quartz/Vision 不在環境では該当テストが skip されるのは許容)

- [ ] **Step 3: 手動確認(ネットワーク＋実PDF)**

1. `python main.py` → 既存PDF(例: 12_シンプリシティ.pdf)を分割メニューから開く。
2. 「目次から章を自動解析」→ 目次ページ範囲・アンカー(印刷p.X=PDF#Y)を指定 →「解析する」。
3. プレビューに章と PDFページ範囲、除外/警告が出ること、確定で章一覧が置換されることを確認。
4. 密な日本語目次で解像度不足なら `render_page_image` の `max_height` を上げる。

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document TOC auto-analyze in existing-PDF split flow"
```

---

## 最終レビュー

全タスク完了後、`claude/pdf-split-toc-analyze` の差分に対して最終 whole-branch レビュー＋Codex レビューをかけ、収束後にマージする。
