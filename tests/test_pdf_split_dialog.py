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


def test_open_toc_analyze_uses_selected_ranges(qapp, pdf_path, monkeypatch):
    """解析ダイアログの selected_ranges（章のみ選択後）を反映すること"""
    class _FakeDialog:
        result_ranges = [
            ChapterRange("1章", 0, 4),
            ChapterRange("第I部", 5, 5),
            ChapterRange("2章", 6, 9),
        ]
        selected_ranges = [ChapterRange("1章", 0, 4), ChapterRange("2章", 6, 9)]

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return True

    monkeypatch.setattr(
        "src.ui.pdf_toc_analyze_dialog.PdfTocAnalyzeDialog", _FakeDialog
    )
    dialog = PdfSplitDialog(pdf_path)
    dialog._open_toc_analyze()
    assert [r.name_edit.text() for r in dialog._chapter_rows] == ["1章", "2章"]
