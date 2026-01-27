# src/export/file_manager.py
"""ファイル管理機能"""

from pathlib import Path
from datetime import date
import shutil


class FileManager:
    """出力ファイルの管理を行うクラス"""

    def __init__(self, base_path: Path | None = None):
        self.base_path = base_path or Path.home() / "Desktop" / "captures"

    def create_output_directory(self, name: str) -> Path:
        """日付付きの出力ディレクトリを作成"""
        today = date.today().strftime("%Y-%m-%d")
        dir_name = f"{today}_{name}"
        output_dir = self.base_path / dir_name
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def get_image_path(self, output_dir: Path, page_number: int) -> Path:
        """ページ番号に対応する画像パスを取得"""
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        return images_dir / f"page_{page_number:03d}.png"

    def cleanup_images(self, output_dir: Path) -> None:
        """画像ディレクトリを削除"""
        images_dir = output_dir / "images"
        if images_dir.exists():
            shutil.rmtree(images_dir)

    def get_chapter_pdf_path(self, output_dir: Path, index: int, name: str) -> Path:
        """章別PDFのパスを取得"""
        # ファイル名に使えない文字を置換
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        return output_dir / f"chapter_{index:02d}_{safe_name}.pdf"
