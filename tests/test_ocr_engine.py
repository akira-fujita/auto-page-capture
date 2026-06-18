# tests/test_ocr_engine.py
import tempfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from src.export.ocr_engine import TextBox

vision = pytest.importorskip("Vision", reason="macOS Vision framework not available")
from src.export.ocr_engine import VisionOcrEngine


def _make_text_image(path: Path, text: str):
    img = Image.new("RGB", (600, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 70), text, fill="black")
    img.save(path, "PNG")


def test_recognizes_latin_text():
    engine = VisionOcrEngine()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "hello.png"
        _make_text_image(path, "HELLO123")
        boxes = engine.recognize(path)
        assert all(isinstance(b, TextBox) for b in boxes)
        joined = "".join(b.text for b in boxes).upper().replace(" ", "")
        assert "HELLO123" in joined
