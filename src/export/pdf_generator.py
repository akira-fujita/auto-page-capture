# src/export/pdf_generator.py
"""PDF生成機能"""

from pathlib import Path
import img2pdf
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

_CJK_FONT = "HeiseiKakuGo-W5"
_font_registered = False


def _ensure_font():
    """日本語出力用CIDフォントを一度だけ登録"""
    global _font_registered
    if not _font_registered:
        pdfmetrics.registerFont(UnicodeCIDFont(_CJK_FONT))
        _font_registered = True


class PdfGenerator:
    """画像からPDFを生成するクラス"""

    def generate(
        self,
        image_paths: list[Path],
        output_path: Path,
        ocr: bool = False,
        ocr_engine=None,
    ) -> None:
        """画像リストからPDFを生成。

        ocr=Trueのとき、各ページに見えないテキストレイヤーを重ねた
        検索可能PDFを生成する。ocr=Falseのときは従来通りの画像PDF。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not ocr:
            paths_str = [str(p) for p in image_paths]
            with open(output_path, "wb") as f:
                f.write(img2pdf.convert(paths_str))
            return

        if ocr_engine is None:
            from src.export.ocr_engine import VisionOcrEngine
            ocr_engine = VisionOcrEngine()

        self._generate_with_ocr(image_paths, output_path, ocr_engine)

    def _generate_with_ocr(self, image_paths, output_path, ocr_engine) -> None:
        _ensure_font()
        c = canvas.Canvas(str(output_path))
        for image_path in image_paths:
            with Image.open(image_path) as im:
                width, height = im.size
            c.setPageSize((width, height))
            c.drawImage(str(image_path), 0, 0, width=width, height=height)

            for box in ocr_engine.recognize(image_path):
                # Vision の boundingBox は正規化(0..1)・左下原点。reportlab の
                # canvas も左下原点なので、Y反転なしで座標がそのまま対応する。
                # テキストは不可視(render mode 3)で描画するため、正確な
                # ベースライン位置はテキスト選択時のハイライト形状に影響する
                # だけで、抽出されるテキスト自体には影響しない。
                x = box.x * width
                y = box.y * height
                font_size = max(box.h * height, 1.0)
                text_obj = c.beginText(x, y)
                text_obj.setFont(_CJK_FONT, font_size)
                text_obj.setTextRenderMode(3)  # 不可視(見た目は画像のまま)
                text_obj.textOut(box.text)
                c.drawText(text_obj)

            c.showPage()
        c.save()
