# tests/test_pdf_generator.py
import pytest
import tempfile
from pathlib import Path
from PIL import Image
from src.export.pdf_generator import PdfGenerator


@pytest.fixture
def sample_images():
    """テスト用のサンプル画像を生成"""
    images = []
    for i in range(3):
        img = Image.new("RGB", (100, 100), color=(i * 50, i * 50, i * 50))
        images.append(img)
    return images


@pytest.fixture
def saved_image_paths(sample_images):
    """サンプル画像をファイルとして保存"""
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = []
        for i, img in enumerate(sample_images):
            path = Path(tmpdir) / f"page_{i:03d}.png"
            img.save(path, "PNG")
            paths.append(path)
        yield paths


def test_generate_pdf_creates_file(saved_image_paths):
    """PDFファイルが生成される"""
    gen = PdfGenerator()
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "output.pdf"
        gen.generate(saved_image_paths, output)
        assert output.exists()
        assert output.stat().st_size > 0


def test_generate_pdf_from_range(saved_image_paths):
    """指定範囲の画像からPDFを生成"""
    gen = PdfGenerator()
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "chapter.pdf"
        # インデックス1-2の画像のみ
        gen.generate(saved_image_paths[1:3], output)
        assert output.exists()
