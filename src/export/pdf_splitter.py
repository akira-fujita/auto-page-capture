# src/export/pdf_splitter.py
"""既存PDFの読み込み・サムネイルレンダリング・章分割"""

from pathlib import Path

from pypdf import PdfReader, PdfWriter
from PyQt6.QtGui import QImage, QPixmap

import Quartz
from CoreFoundation import CFURLCreateWithFileSystemPath, kCFAllocatorDefault, kCFURLPOSIXPathStyle

from src.export.file_manager import FileManager


class PdfSplitter:
    """既存PDFの読み込み・分割を行うクラス"""

    def __init__(self):
        self.file_manager = FileManager()

    def detect_chapters(self, pdf_path: Path) -> list[tuple[str, int]]:
        """PDFのブックマーク（アウトライン）から章情報を自動検出

        Args:
            pdf_path: PDFファイルパス

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
            title = item.get("/Title", "")
            page_num = reader.get_destination_page_number(item)
            chapters.append((title, page_num + 1))  # 1-indexed

        chapters.sort(key=lambda c: c[1])
        return chapters

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
        # CGPDFDocument のページ番号は 1-indexed
        page = Quartz.CGPDFDocumentGetPage(pdf_doc, page_index + 1)

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
