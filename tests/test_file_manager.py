# tests/test_file_manager.py
import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from src.export.file_manager import FileManager


def test_create_output_directory():
    """出力ディレクトリが作成される"""
    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager(base_path=Path(tmpdir))
        output_dir = fm.create_output_directory("test_capture")
        assert output_dir.exists()
        assert "test_capture" in output_dir.name


def test_output_directory_includes_datetime():
    """出力ディレクトリ名に日時が含まれる"""
    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager(base_path=Path(tmpdir))
        output_dir = fm.create_output_directory("capture")
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in output_dir.name
        # 時刻部分も含まれていることを確認（形式: HHMMSS）
        assert "_" in output_dir.name.replace(today, "")


def test_get_image_path():
    """ページ番号に応じた画像パスを取得"""
    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager(base_path=Path(tmpdir))
        output_dir = fm.create_output_directory("test")
        path = fm.get_image_path(output_dir, 5)
        assert path.name == "page_005.png"


def test_cleanup_images():
    """画像ファイルが削除される"""
    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager(base_path=Path(tmpdir))
        output_dir = fm.create_output_directory("test")
        images_dir = output_dir / "images"
        images_dir.mkdir()

        # ダミー画像を作成
        (images_dir / "page_001.png").touch()
        (images_dir / "page_002.png").touch()

        fm.cleanup_images(output_dir)
        assert not images_dir.exists()
