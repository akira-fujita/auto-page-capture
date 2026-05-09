# tests/test_pdf_split_dialog.py
"""PDF分割ダイアログのUIテスト"""

import pytest
import tempfile
from pathlib import Path
from pypdf import PdfWriter
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt

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
    """自動検出後も章を編集・削除・追加できる"""
    dialog = PdfSplitDialog(pdf_with_bookmarks)
    dialog._on_auto_detect()
    # 章名を変更できる
    dialog._chapter_rows[0].name_edit.setText("序章")
    assert dialog._chapter_rows[0].name_edit.text() == "序章"
    # 開始ページを変更できる
    dialog._chapter_rows[0].start_spin.setValue(2)
    assert dialog._chapter_rows[0].start_spin.value() == 2
    # 自動検出された章を削除できる
    dialog._chapter_rows[1].delete_btn.click()
    assert len(dialog._chapter_rows) == 2
    # 章を追加できる
    dialog._on_add_chapter()
    assert len(dialog._chapter_rows) == 3
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


def test_auto_detect_confirms_before_overwriting_edited_chapters(pdf_with_bookmarks, monkeypatch):
    """編集済みの章がある場合、自動検出前に確認ダイアログを表示する"""
    dialog = PdfSplitDialog(pdf_with_bookmarks)
    # 章名を編集して「編集済み」状態にする
    dialog._chapter_rows[0].name_edit.setText("カスタム章名")

    # ユーザーがキャンセルした場合
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No
    )
    dialog._on_auto_detect()
    # キャンセルしたので既存の章が維持される
    assert len(dialog._chapter_rows) == 1
    assert dialog._chapter_rows[0].name_edit.text() == "カスタム章名"
    dialog.close()


def test_auto_detect_overwrites_when_user_confirms(pdf_with_bookmarks, monkeypatch):
    """ユーザーが確認に同意した場合、編集済み章を上書きする"""
    dialog = PdfSplitDialog(pdf_with_bookmarks)
    dialog._chapter_rows[0].name_edit.setText("カスタム章名")

    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    dialog._on_auto_detect()
    # 上書きされてブックマークの章が設定される
    assert len(dialog._chapter_rows) == 3
    dialog.close()


def test_auto_detect_no_confirm_for_default_chapters(pdf_with_bookmarks, monkeypatch):
    """デフォルト状態（未編集）の章には確認なしで自動検出する"""
    question_called = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: question_called.append(True) or QMessageBox.StandardButton.Yes
    )
    dialog = PdfSplitDialog(pdf_with_bookmarks)
    # 初期状態のまま自動検出
    dialog._on_auto_detect()
    assert len(question_called) == 0, "デフォルト状態では確認ダイアログは不要"
    assert len(dialog._chapter_rows) == 3
    dialog.close()


def test_auto_detect_prepends_page1_chapter(monkeypatch):
    """先頭ブックマークがp.1でない場合、p.1から始まる補完章を追加する"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "no_page1.pdf"
        writer = PdfWriter()
        for _ in range(20):
            writer.add_blank_page(width=612, height=792)
        # ブックマークはp.5から
        writer.add_outline_item("第1章", 4)  # 0-indexed: 4 = p.5
        writer.add_outline_item("第2章", 9)  # 0-indexed: 9 = p.10
        with open(pdf_path, "wb") as f:
            writer.write(f)

        dialog = PdfSplitDialog(pdf_path)
        dialog._on_auto_detect()
        rows = sorted(dialog._chapter_rows, key=lambda r: r.start_spin.value())
        # p.1からの補完章が追加されている
        assert rows[0].start_spin.value() == 1, "冒頭ページが欠落している"
        assert rows[1].start_spin.value() == 5
        assert rows[2].start_spin.value() == 10
        assert len(rows) == 3
        dialog.close()


def test_auto_detect_no_prepend_when_starts_at_page1(pdf_with_bookmarks):
    """先頭ブックマークがp.1の場合、補完章は追加しない"""
    dialog = PdfSplitDialog(pdf_with_bookmarks)
    dialog._on_auto_detect()
    rows = sorted(dialog._chapter_rows, key=lambda r: r.start_spin.value())
    assert rows[0].start_spin.value() == 1
    # ブックマーク数と一致（余計な章が追加されていない）
    assert len(rows) == 3
    dialog.close()


def test_spinbox_accepts_three_digit_key_input(sample_pdf_500):
    """キー入力で3桁のページ番号を入力できる（回帰テスト）"""
    dialog = PdfSplitDialog(sample_pdf_500)
    row = dialog._chapter_rows[0]
    line_edit = row.start_spin.lineEdit()
    # 既存テキストをクリアしてからキー入力
    line_edit.selectAll()
    QTest.keyClicks(line_edit, "456")
    assert row.start_spin.value() == 456, "3桁のキー入力が受け付けられない"
    display = line_edit.displayText()
    assert "456" in display, f"表示が切れている: {display}"
    dialog.close()


def test_auto_detect_handles_exception_gracefully(sample_pdf_500, monkeypatch):
    """detect_chapters()が例外を投げた場合、エラーメッセージを表示し既存章を保持する"""
    dialog = PdfSplitDialog(sample_pdf_500)
    # 章を編集しておく
    dialog._chapter_rows[0].name_edit.setText("手動入力済み")

    # detect_chapters が例外を投げるようにする
    monkeypatch.setattr(
        dialog.splitter, "detect_chapters",
        lambda path: (_ for _ in ()).throw(RuntimeError("壊れたPDF"))
    )

    critical_messages = []
    monkeypatch.setattr(
        QMessageBox, "critical",
        lambda *args, **kwargs: critical_messages.append(args)
    )

    dialog._on_auto_detect()

    # エラーメッセージが表示される
    assert len(critical_messages) == 1
    # 既存の章入力が保持される
    assert len(dialog._chapter_rows) == 1
    assert dialog._chapter_rows[0].name_edit.text() == "手動入力済み"
    dialog.close()
