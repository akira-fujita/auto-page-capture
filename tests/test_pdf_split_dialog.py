# tests/test_pdf_split_dialog.py
"""PDF分割ダイアログのUIテスト"""

import pytest
import tempfile
from pathlib import Path
from pypdf import PdfWriter
from PyQt6.QtWidgets import QApplication, QMessageBox

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


def test_spinbox_has_no_prefix(sample_pdf_500):
    """QSpinBoxにprefixが設定されていない（別ラベルで表示する）"""
    dialog = PdfSplitDialog(sample_pdf_500)
    row = dialog._chapter_rows[0]
    assert row.start_spin.prefix() == "", (
        "QSpinBoxにprefixがあると3桁入力時にバリデーション問題が発生する"
    )
    dialog.close()


def test_chapter_row_has_page_label(sample_pdf_500):
    """章行に「開始: p.」ラベルが存在する"""
    dialog = PdfSplitDialog(sample_pdf_500)
    row = dialog._chapter_rows[0]
    assert hasattr(row, "page_label"), "ページラベルが存在しない"
    assert "p." in row.page_label.text()
    dialog.close()


def test_spinbox_accepts_three_digit_value(sample_pdf_500):
    """3桁のページ番号を設定できる"""
    dialog = PdfSplitDialog(sample_pdf_500)
    row = dialog._chapter_rows[0]
    row.start_spin.setValue(456)
    assert row.start_spin.value() == 456
    dialog.close()


def test_spinbox_max_matches_page_count(sample_pdf_500):
    """SpinBoxの最大値がPDFのページ数と一致する"""
    dialog = PdfSplitDialog(sample_pdf_500)
    row = dialog._chapter_rows[0]
    assert row.start_spin.maximum() == 500
    dialog.close()


@pytest.fixture
def pdf_with_bookmarks():
    """ブックマーク付きPDFを生成"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "bookmarked.pdf"
        writer = PdfWriter()
        for _ in range(10):
            writer.add_blank_page(width=612, height=792)
        writer.add_outline_item("はじめに", 0)
        writer.add_outline_item("第1章 基礎", 2)
        writer.add_outline_item("第2章 応用", 5)
        with open(pdf_path, "wb") as f:
            writer.write(f)
        yield pdf_path


def test_auto_detect_button_exists(sample_pdf_500):
    """自動検出ボタンが存在する"""
    dialog = PdfSplitDialog(sample_pdf_500)
    assert hasattr(dialog, "_detect_btn"), "自動検出ボタンが存在しない"
    dialog.close()


def test_auto_detect_populates_chapters(pdf_with_bookmarks):
    """自動検出でブックマークから章行が作成される"""
    dialog = PdfSplitDialog(pdf_with_bookmarks)
    dialog._on_auto_detect()
    assert len(dialog._chapter_rows) == 3
    # 章名と開始ページの確認
    rows = sorted(dialog._chapter_rows, key=lambda r: r.start_spin.value())
    assert rows[0].name_edit.text() == "はじめに"
    assert rows[0].start_spin.value() == 1
    assert rows[1].name_edit.text() == "第1章 基礎"
    assert rows[1].start_spin.value() == 3
    assert rows[2].name_edit.text() == "第2章 応用"
    assert rows[2].start_spin.value() == 6
    dialog.close()


def test_auto_detect_chapters_are_editable(pdf_with_bookmarks):
    """自動検出後も章を編集できる"""
    dialog = PdfSplitDialog(pdf_with_bookmarks)
    dialog._on_auto_detect()
    # 章名を変更できる
    dialog._chapter_rows[0].name_edit.setText("序章")
    assert dialog._chapter_rows[0].name_edit.text() == "序章"
    # 開始ページを変更できる
    dialog._chapter_rows[0].start_spin.setValue(2)
    assert dialog._chapter_rows[0].start_spin.value() == 2
    # 章を追加できる
    dialog._on_add_chapter()
    assert len(dialog._chapter_rows) == 4
    dialog.close()


def test_auto_detect_no_bookmarks_shows_message(sample_pdf_500, monkeypatch):
    """ブックマークがない場合にメッセージが表示される"""
    shown_messages = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *args, **kwargs: shown_messages.append(args)
    )
    dialog = PdfSplitDialog(sample_pdf_500)
    dialog._on_auto_detect()
    assert len(shown_messages) == 1
    # 既存の章行は変更されない（初期の1章のまま）
    assert len(dialog._chapter_rows) == 1
    dialog.close()
