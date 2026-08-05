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


def test_create_split_output_directory_uses_timestamp_and_source_name():
    """PDF分割用サブフォルダが timestamp_<元PDF名> 形式で作成される"""
    import re
    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager()
        parent = Path(tmpdir)
        sub = fm.create_split_output_directory(parent, "oreilly-978-4-8144-0156-7e")
        assert sub.exists()
        assert sub.parent == parent
        # YYYY-MM-DD_HHMMSS_oreilly-978-4-8144-0156-7e
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}_\d{6}_oreilly-978-4-8144-0156-7e$",
            sub.name,
        )


def test_create_split_output_directory_sanitizes_unsafe_chars():
    """ファイル名に使えない文字はアンダースコアに置換される"""
    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager()
        parent = Path(tmpdir)
        sub = fm.create_split_output_directory(parent, "foo/bar:baz")
        assert sub.exists()
        # /と:が_に置換される
        assert "/" not in sub.name
        assert ":" not in sub.name
        assert sub.name.endswith("_foo_bar_baz")


def test_create_split_output_directory_creates_unique_dirs_per_call():
    """連続呼び出しで異なるディレクトリが作られ既存を上書きしない"""
    import time
    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager()
        parent = Path(tmpdir)
        sub1 = fm.create_split_output_directory(parent, "sample")
        time.sleep(1.1)  # タイムスタンプ解像度は秒
        sub2 = fm.create_split_output_directory(parent, "sample")
        assert sub1 != sub2
        assert sub1.exists() and sub2.exists()
