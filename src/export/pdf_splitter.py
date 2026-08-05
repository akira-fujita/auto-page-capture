# src/export/pdf_splitter.py
"""既存PDFの読み込み・サムネイルレンダリング・章分割"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pypdf import PdfReader, PdfWriter
from PyQt6.QtGui import QImage, QPixmap

import Quartz
from CoreFoundation import CFURLCreateWithFileSystemPath, kCFAllocatorDefault, kCFURLPOSIXPathStyle

from src.export.file_manager import FileManager
from src.export.toc_detector import detect_chapters_from_text, has_text_layer

# OCR向け後処理のコントラスト強調係数。淡色の目次を確実に読ませるための調整ノブ。
_OCR_CONTRAST_FACTOR = 4.0


def _enhance_for_ocr(image_path: Path) -> None:
    """画像をグレースケール化してコントラストを強調し、その場で上書き保存する。

    淡色（薄いグレー/黄色など）でレンダリングされた目次でも claude が
    確実に読めるようにするための後処理。
    """
    from PIL import Image, ImageOps, ImageEnhance

    with Image.open(image_path) as im:
        gray = ImageOps.grayscale(im.convert("RGB"))
        enhanced = ImageEnhance.Contrast(gray).enhance(_OCR_CONTRAST_FACTOR)
        enhanced.save(image_path, "PNG")


@dataclass(frozen=True)
class DetectionResult:
    """claude を使わない章検出の結果

    chapters: (章名, 開始ページ 1-indexed) のリスト
    source: "bookmark"=しおり / "heading"=本文見出し / "toc"=目次の印字ページ / "none"=検出なし
    has_text_layer: PDF がテキスト層を持つか（False はスキャン PDF の可能性）
    """

    chapters: list[tuple[str, int]]
    source: Literal["bookmark", "heading", "toc", "none"]
    has_text_layer: bool


class PdfSplitter:
    """既存PDFの読み込み・分割を行うクラス"""

    def __init__(self):
        self.file_manager = FileManager()

    def detect_bookmark_chapters(self, pdf_path: Path) -> list[tuple[str, int]]:
        """PDFのブックマーク（アウトライン）から章情報を取得

        Returns:
            (章名, 開始ページ番号(1-indexed)) のリスト。ページ番号順。
            検出できない場合は空リスト。
        """
        reader = PdfReader(str(pdf_path))
        outlines = reader.outline
        if not outlines:
            return []

        chapters = []
        for item in outlines:
            # ネストされたブックマーク（リスト）はスキップ（トップレベルのみ）
            if isinstance(item, list):
                continue
            title = str(item.get("/Title", "")).strip()
            if not title:
                continue
            page_num = reader.get_destination_page_number(item)
            chapters.append((title, page_num + 1))  # 1-indexed

        chapters.sort(key=lambda c: c[1])
        return chapters

    def extract_page_texts(self, pdf_path: Path) -> list[str]:
        """各ページのテキストを取得（index 0 が p.1）

        テキストを持たないページや抽出に失敗したページは空文字にする。
        """
        reader = PdfReader(str(pdf_path))
        texts = []
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            texts.append(text)
        return texts

    def detect_chapters_auto(self, pdf_path: Path) -> DetectionResult:
        """claude を使わずに章を検出する（ブックマーク優先、無ければ本文テキスト）"""
        bookmarks = self.detect_bookmark_chapters(pdf_path)
        if bookmarks:
            return DetectionResult(bookmarks, "bookmark", True)

        page_texts = self.extract_page_texts(pdf_path)
        if not has_text_layer(page_texts):
            return DetectionResult([], "none", False)

        text_result = detect_chapters_from_text(page_texts)
        return DetectionResult(text_result.chapters, text_result.source, True)

    def get_page_count(self, pdf_path: Path) -> int:
        """PDFのページ数を取得"""
        reader = PdfReader(str(pdf_path))
        return len(reader.pages)

    def render_page_thumbnail(self, pdf_path: Path, page_index: int, max_height: int = 140) -> QPixmap:
        """PDFページをサムネイル画像としてレンダリング（macOS Quartz使用）"""
        url = CFURLCreateWithFileSystemPath(
            kCFAllocatorDefault, str(pdf_path), kCFURLPOSIXPathStyle, False
        )
        pdf_doc = Quartz.CGPDFDocumentCreateWithURL(url)
        if pdf_doc is None:
            raise RuntimeError(f"PDFを読み込めませんでした: {pdf_path}")
        # CGPDFDocument のページ番号は 1-indexed
        page = Quartz.CGPDFDocumentGetPage(pdf_doc, page_index + 1)
        if page is None:
            raise RuntimeError(f"PDFページを読み込めませんでした (page {page_index + 1})")

        page_rect = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
        page_width = page_rect.size.width
        page_height = page_rect.size.height

        # max_height に収まるようスケーリング
        scale = max_height / page_height
        render_width = int(page_width * scale)
        render_height = int(page_height * scale)

        # ビットマップコンテキストを作成
        color_space = Quartz.CGColorSpaceCreateDeviceRGB()
        context = Quartz.CGBitmapContextCreate(
            None, render_width, render_height, 8, render_width * 4,
            color_space, Quartz.kCGImageAlphaPremultipliedFirst
        )

        # 背景を白に
        Quartz.CGContextSetRGBFillColor(context, 1.0, 1.0, 1.0, 1.0)
        Quartz.CGContextFillRect(context, Quartz.CGRectMake(0, 0, render_width, render_height))

        # PDFページを描画
        Quartz.CGContextScaleCTM(context, scale, scale)
        Quartz.CGContextDrawPDFPage(context, page)

        # CGImage → QPixmap
        cg_image = Quartz.CGBitmapContextCreateImage(context)
        width = Quartz.CGImageGetWidth(cg_image)
        height = Quartz.CGImageGetHeight(cg_image)
        bytes_per_row = Quartz.CGImageGetBytesPerRow(cg_image)
        data_provider = Quartz.CGImageGetDataProvider(cg_image)
        data = Quartz.CGDataProviderCopyData(data_provider)

        qimage = QImage(data, width, height, bytes_per_row, QImage.Format.Format_ARGB32_Premultiplied)
        pixmap = QPixmap.fromImage(qimage.copy())
        return pixmap

    def render_page_image(
        self, pdf_path: Path, page_index: int, output_path: Path, max_height: int = 2000
    ) -> Path:
        """PDFページを OCR 向けの高解像度PNGとして保存し、そのパスを返す。

        max_height は解像度ノブ。淡色（薄いグレー/黄色など）の目次でも
        claude が確実に読めるよう、グレースケール化してコントラストを
        強調してから保存する。
        """
        pixmap = self.render_page_thumbnail(pdf_path, page_index, max_height=max_height)
        if not pixmap.save(str(output_path), "PNG"):
            raise RuntimeError(f"PDFページ画像の保存に失敗しました: {output_path}")
        # OCR向けの後処理: グレースケール + コントラスト強調
        _enhance_for_ocr(output_path)
        return output_path

    def split(self, pdf_path: Path, chapters: list, output_dir: Path) -> list[Path]:
        """PDFを章ごとに分割して保存

        Args:
            pdf_path: 元PDFのパス
            chapters: Chapter オブジェクトのリスト（start, end, name属性を持つ）
            output_dir: 出力ディレクトリ

        Returns:
            生成されたPDFファイルパスのリスト
        """
        reader = PdfReader(str(pdf_path))
        output_paths = []

        for i, chapter in enumerate(chapters):
            writer = PdfWriter()
            for page_idx in range(chapter.start, chapter.end + 1):
                writer.add_page(reader.pages[page_idx])

            pdf_out = self.file_manager.get_chapter_pdf_path(
                output_dir, i + 1, chapter.name
            )
            with open(pdf_out, "wb") as f:
                writer.write(f)
            output_paths.append(pdf_out)

        return output_paths
