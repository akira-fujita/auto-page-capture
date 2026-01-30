# tests/test_integration.py
"""統合テスト"""

import pytest
import tempfile
from pathlib import Path
from PIL import Image
from src.capture.window_manager import WindowManager
from src.capture.screenshot import Screenshot
from src.capture.page_navigator import PageNavigator, Direction
from src.export.pdf_generator import PdfGenerator
from src.export.file_manager import FileManager


def test_full_workflow():
    """キャプチャからPDF生成までの一連の流れ"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # FileManagerでディレクトリ作成
        fm = FileManager(base_path=Path(tmpdir))
        output_dir = fm.create_output_directory("test")

        # 仮の画像を作成（実際のキャプチャの代わり）
        image_paths = []
        for i in range(5):
            img = Image.new("RGB", (200, 300), color=(i * 40, 100, 150))
            path = fm.get_image_path(output_dir, i + 1)
            img.save(path, "PNG")
            image_paths.append(path)

        # PDF生成
        pdf_gen = PdfGenerator()

        # 全体PDF
        output_pdf = output_dir / "output.pdf"
        pdf_gen.generate(image_paths, output_pdf)
        assert output_pdf.exists()

        # 章別PDF
        chapter1_pdf = fm.get_chapter_pdf_path(output_dir, 1, "第1章")
        pdf_gen.generate(image_paths[:2], chapter1_pdf)
        assert chapter1_pdf.exists()

        chapter2_pdf = fm.get_chapter_pdf_path(output_dir, 2, "第2章")
        pdf_gen.generate(image_paths[2:], chapter2_pdf)
        assert chapter2_pdf.exists()


def test_window_manager_integration():
    """WindowManagerが実際のウィンドウ一覧を取得できる"""
    wm = WindowManager()
    windows = wm.get_window_list()
    # macOSで実行すれば少なくとも1つはウィンドウがあるはず
    # CI環境ではスキップ
    if windows:
        assert all("id" in w for w in windows)
        assert all("bounds" in w for w in windows)
