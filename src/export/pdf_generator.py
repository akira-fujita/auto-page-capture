# src/export/pdf_generator.py
"""PDF生成機能"""

from pathlib import Path
import img2pdf


class PdfGenerator:
    """画像からPDFを生成するクラス"""

    def generate(self, image_paths: list[Path], output_path: Path) -> None:
        """画像リストからPDFを生成"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # パスを文字列に変換
        paths_str = [str(p) for p in image_paths]

        with open(output_path, "wb") as f:
            f.write(img2pdf.convert(paths_str))
