# tests/test_pdf_splitter.py
import pytest
import tempfile
from dataclasses import dataclass
from pathlib import Path
from pypdf import PdfWriter, PdfReader

from src.export.pdf_splitter import PdfSplitter


@dataclass
class _Chapter:
    name: str
    start: int
    end: int


@pytest.fixture
def sample_pdf():
    """テスト用の5ページPDFを生成"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "sample.pdf"
        writer = PdfWriter()
        for _ in range(5):
            writer.add_blank_page(width=612, height=792)
        with open(pdf_path, "wb") as f:
            writer.write(f)
        yield pdf_path


@pytest.fixture
def splitter():
    return PdfSplitter()


def test_get_page_count(splitter, sample_pdf):
    """ページ数を正しく取得できる"""
    assert splitter.get_page_count(sample_pdf) == 5


def test_split_creates_files(splitter, sample_pdf):
    """章分割でファイルが生成される"""
    chapters = [
        _Chapter(name="第1章", start=0, end=1),
        _Chapter(name="第2章", start=2, end=4),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        paths = splitter.split(sample_pdf, chapters, output_dir)
        assert len(paths) == 2
        for p in paths:
            assert p.exists()
            assert p.stat().st_size > 0


def test_split_page_count(splitter, sample_pdf):
    """分割後のPDFが正しいページ数を持つ"""
    chapters = [
        _Chapter(name="前半", start=0, end=2),
        _Chapter(name="後半", start=3, end=4),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        paths = splitter.split(sample_pdf, chapters, output_dir)

        reader1 = PdfReader(str(paths[0]))
        reader2 = PdfReader(str(paths[1]))
        assert len(reader1.pages) == 3
        assert len(reader2.pages) == 2


def test_split_single_chapter(splitter, sample_pdf):
    """1章のみの場合も正常に分割できる"""
    chapters = [_Chapter(name="全体", start=0, end=4)]
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        paths = splitter.split(sample_pdf, chapters, output_dir)
        assert len(paths) == 1
        reader = PdfReader(str(paths[0]))
        assert len(reader.pages) == 5


def test_split_file_names_have_chapter_number(splitter, sample_pdf):
    """分割ファイル名に章番号が含まれる"""
    chapters = [
        _Chapter(name="はじめに", start=0, end=1),
        _Chapter(name="本編", start=2, end=4),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        paths = splitter.split(sample_pdf, chapters, output_dir)
        assert "chapter_01_" in paths[0].name
        assert "chapter_02_" in paths[1].name
