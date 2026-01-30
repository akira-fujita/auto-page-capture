# tests/test_screenshot.py
import pytest
import tempfile
import os
from pathlib import Path
from PIL import Image
from src.capture.screenshot import Screenshot


def test_capture_region_returns_image():
    """指定領域のスクリーンショットがPIL Imageで返される"""
    ss = Screenshot()
    # 小さい領域でテスト
    image = ss.capture_region(0, 0, 100, 100)
    assert isinstance(image, Image.Image)
    assert image.size == (100, 100)


def test_save_image_creates_file():
    """画像がファイルとして保存される"""
    ss = Screenshot()
    image = ss.capture_region(0, 0, 100, 100)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.png"
        ss.save_image(image, path)
        assert path.exists()
        # 保存した画像が読み込める
        saved = Image.open(path)
        assert saved.size == (100, 100)
