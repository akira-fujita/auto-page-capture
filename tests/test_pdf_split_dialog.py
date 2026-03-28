# tests/test_pdf_split_dialog.py
"""PDF分割ダイアログのUIテスト"""

import pytest
import tempfile
from pathlib import Path
from pypdf import PdfWriter
from PyQt6.QtWidgets import QApplication

from src.ui.pdf_split_dialog import PdfSplitDialog, _ChapterRow

# PyQt6テストにはQApplicationインスタンスが必要
app = QApplication.instance() or QApplication([])


@pytest.fixture
def sample_pdf_500():
    """テスト用の500ページPDFを生成"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "sample_500.pdf"
        writer = PdfWriter()
        for _ in range(500):
            writer.add_blank_page(width=612, height=792)
        with open(pdf_path, "wb") as f:
            writer.write(f)
        yield pdf_path


def test_spinbox_accepts_three_digit_pages(sample_pdf_500):
    """3桁のページ番号を入力できる"""
    dialog = PdfSplitDialog(sample_pdf_500)

    row = dialog._chapter_rows[0]
    row.start_spin.setValue(999)

    # QSpinBoxのテキスト表示がクリップされないよう十分な幅がある
    # minimumWidth が prefix + 3桁数字 + マージンを収容できること
    min_width = row.start_spin.minimumWidth()
    assert min_width >= 140, (
        f"QSpinBoxのminimumWidth ({min_width}px) が3桁ページ番号に対して不十分"
    )
    dialog.close()


def test_spinbox_max_matches_page_count(sample_pdf_500):
    """SpinBoxの最大値がPDFのページ数と一致する"""
    dialog = PdfSplitDialog(sample_pdf_500)

    row = dialog._chapter_rows[0]
    assert row.start_spin.maximum() == 500
    dialog.close()
