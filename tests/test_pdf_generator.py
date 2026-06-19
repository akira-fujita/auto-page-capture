# tests/test_pdf_generator.py
import pytest
import tempfile
from pathlib import Path
import img2pdf
from PIL import Image
from pypdf import PdfReader
from src.export.pdf_generator import PdfGenerator
from src.export.ocr_engine import TextBox


class FakeOcrEngine:
    """既知のテキストボックスを返すテスト用エンジン"""

    def __init__(self, boxes):
        self._boxes = boxes
        self.calls = []

    def recognize(self, image_path):
        self.calls.append(image_path)
        return self._boxes


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


def test_generate_without_ocr_matches_img2pdf_bytes(saved_image_paths):
    """ocr=False(既定)の出力が従来のimg2pdf経路とバイト単位で一致する(後方互換)"""
    expected = img2pdf.convert([str(p) for p in saved_image_paths])
    gen = PdfGenerator()
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "image_only.pdf"
        gen.generate(saved_image_paths, output)
        actual = output.read_bytes()
        assert actual == expected
