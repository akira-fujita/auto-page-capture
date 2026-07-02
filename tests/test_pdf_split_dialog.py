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
from src.ui.pdf_split_dialog import PdfSplitDialog, excluded_page_ranges


def test_excluded_page_ranges_basic():
    # chapters(0始まり包含): 16-19, 22-39 / 全40ページ
    # 除外index: 0-15, 20-21 → 1始まり p.1-16, p.21-22
    assert excluded_page_ranges([(16, 19), (22, 39)], 40) == [(1, 16), (21, 22)]


def test_excluded_page_ranges_trailing_backmatter():
    # 最終章が末尾前で止まる → 末尾が除外される
    assert excluded_page_ranges([(0, 3)], 10) == [(5, 10)]


def test_excluded_page_ranges_none_when_contiguous():
    assert excluded_page_ranges([(0, 4), (5, 9)], 10) == []


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


def test_selected_ranges_preserve_gaps_not_absorbed(qapp, pdf_path, monkeypatch):
    """除外行のページが隣接章に吸収されないこと（範囲不変）"""
    class _FakeDialog:
        # 第I部(page5)と巻末(page9)を除外した想定。ギャップが空く。
        selected_ranges = [ChapterRange("1章", 0, 4), ChapterRange("2章", 6, 7)]

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return True

    monkeypatch.setattr(
        "src.ui.pdf_toc_analyze_dialog.PdfTocAnalyzeDialog", _FakeDialog
    )
    dialog = PdfSplitDialog(pdf_path)
    dialog._open_toc_analyze()
    chapters = dialog._build_chapters()
    # 1章は page5 を吸収せず 0..4、2章は末尾を吸収せず 6..7 のまま
    assert (chapters[0].start, chapters[0].end) == (0, 4)
    assert (chapters[1].start, chapters[1].end) == (6, 7)

    # 実分割まで通し、除外ページ(index 5, 8, 9)がどの出力にも含まれないことを確認
    from pypdf import PdfReader
    out_dir = pdf_path.parent / "split_out"
    out_dir.mkdir()
    outs = dialog.splitter.split(pdf_path, chapters, out_dir)
    page_counts = [len(PdfReader(str(o)).pages) for o in outs]
    assert page_counts == [5, 2]  # 0..4=5ページ, 6..7=2ページ（計7 < 全10）


def test_editing_start_does_not_cause_overlap(qapp, pdf_path, monkeypatch):
    """TOC由来の start を隣の explicit_end より手前に動かしても重複出力しない"""
    class _FakeDialog:
        selected_ranges = [ChapterRange("1章", 0, 4), ChapterRange("2章", 6, 7)]

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return True

    monkeypatch.setattr(
        "src.ui.pdf_toc_analyze_dialog.PdfTocAnalyzeDialog", _FakeDialog
    )
    dialog = PdfSplitDialog(pdf_path)
    dialog._open_toc_analyze()
    # 除外ページのサマリが表示される（index5→p.6, 末尾 idx8,9→p.9-10）
    txt = dialog.excluded_label.text()
    assert "p.6" in txt and "p.9-10" in txt
    # 2章の開始を p.4 (=index3) に手前へ動かす（1章の explicit_end=5 と衝突しうる）
    rows = sorted(dialog._chapter_rows, key=lambda r: r.start_spin.value())
    rows[1].start_spin.setValue(4)
    chapters = dialog._build_chapters()
    chapters.sort(key=lambda c: c.start)
    # 章範囲が重複しない（前章 end < 次章 start）
    assert chapters[0].end < chapters[1].start
