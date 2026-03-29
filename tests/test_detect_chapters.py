# tests/test_detect_chapters.py
"""章自動検出のテスト"""

import pytest
import tempfile
from pathlib import Path
from pypdf import PdfWriter

from src.export.pdf_splitter import PdfSplitter


@pytest.fixture
def splitter():
    return PdfSplitter()


@pytest.fixture
def pdf_with_bookmarks():
    """ブックマーク付きPDFを生成"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "bookmarked.pdf"
        writer = PdfWriter()
        for _ in range(10):
            writer.add_blank_page(width=612, height=792)

        # ブックマークを追加（pypdfのadd_outline_item）
        writer.add_outline_item("はじめに", 0)  # page 0 = p.1
        writer.add_outline_item("第1章 基礎", 2)  # page 2 = p.3
        writer.add_outline_item("第2章 応用", 5)  # page 5 = p.6

        with open(pdf_path, "wb") as f:
            writer.write(f)
        yield pdf_path


@pytest.fixture
def pdf_with_nested_bookmarks():
    """ネストされたブックマーク付きPDFを生成"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "nested.pdf"
        writer = PdfWriter()
        for _ in range(10):
            writer.add_blank_page(width=612, height=792)

        # トップレベルのブックマーク
        ch1 = writer.add_outline_item("第1章", 0)
        # 子ブックマーク
        writer.add_outline_item("1.1 概要", 1, parent=ch1)
        writer.add_outline_item("1.2 詳細", 3, parent=ch1)
        ch2 = writer.add_outline_item("第2章", 5)
        writer.add_outline_item("2.1 概要", 6, parent=ch2)

        with open(pdf_path, "wb") as f:
            writer.write(f)
        yield pdf_path


@pytest.fixture
def pdf_without_bookmarks():
    """ブックマークなしのPDFを生成"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "plain.pdf"
        writer = PdfWriter()
        for _ in range(5):
            writer.add_blank_page(width=612, height=792)
        with open(pdf_path, "wb") as f:
            writer.write(f)
        yield pdf_path


def test_detect_from_bookmarks(splitter, pdf_with_bookmarks):
    """ブックマークから章を検出できる"""
    chapters = splitter.detect_chapters(pdf_with_bookmarks)
    assert len(chapters) == 3
    assert chapters[0] == ("はじめに", 1)   # 1-indexed
    assert chapters[1] == ("第1章 基礎", 3)
    assert chapters[2] == ("第2章 応用", 6)


def test_detect_from_nested_bookmarks_uses_top_level(splitter, pdf_with_nested_bookmarks):
    """ネストされたブックマークではトップレベルのみ使用"""
    chapters = splitter.detect_chapters(pdf_with_nested_bookmarks)
    assert len(chapters) == 2
    assert chapters[0] == ("第1章", 1)
    assert chapters[1] == ("第2章", 6)


def test_detect_returns_empty_for_no_bookmarks(splitter, pdf_without_bookmarks):
    """ブックマークがない場合は空リストを返す"""
    chapters = splitter.detect_chapters(pdf_without_bookmarks)
    assert chapters == []


def test_detect_chapters_sorted_by_page(splitter):
    """検出結果はページ番号順にソートされる"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "unsorted.pdf"
        writer = PdfWriter()
        for _ in range(10):
            writer.add_blank_page(width=612, height=792)

        # 逆順でブックマークを追加
        writer.add_outline_item("後半", 7)
        writer.add_outline_item("前半", 0)
        writer.add_outline_item("中盤", 3)

        with open(pdf_path, "wb") as f:
            writer.write(f)

        chapters = splitter.detect_chapters(pdf_path)
        pages = [page for _, page in chapters]
        assert pages == sorted(pages)
