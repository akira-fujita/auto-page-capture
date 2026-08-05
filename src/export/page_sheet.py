# src/export/page_sheet.py
"""PDFページをサムネイル格子（コンタクトシート）画像にまとめる

テキスト層を持たない PDF の章扉を視覚的に探すための入力を作る。
"""

from pathlib import Path
from typing import Callable

import Quartz
from CoreFoundation import (
    CFURLCreateWithFileSystemPath,
    kCFAllocatorDefault,
    kCFURLPOSIXPathStyle,
)

# サムネイル1枚のサイズ（章扉のレイアウトと章番号が判別できるサイズ）
THUMB_WIDTH = 240
THUMB_HEIGHT = 320
COLUMNS = 6


class SheetCancelled(Exception):
    """描画中にキャンセルされた"""


def sheet_ranges(page_count: int, per_sheet: int) -> list[list[int]]:
    """ページ番号（1-indexed）を1枚あたり per_sheet 枚ずつに区切る"""
    if per_sheet <= 0:
        raise ValueError(f"per_sheet は1以上にしてください: {per_sheet}")
    return [
        list(range(start, min(start + per_sheet, page_count + 1)))
        for start in range(1, page_count + 1, per_sheet)
    ]


def build_contact_sheet(
    pdf_path: Path,
    pages: list[int],
    out_path: Path,
    columns: int = COLUMNS,
    thumb_width: int = THUMB_WIDTH,
    thumb_height: int = THUMB_HEIGHT,
    is_cancelled: Callable[[], bool] | None = None,
) -> str:
    """pages のサムネイルを格子に並べた PNG を書き出し、そのパスを返す

    columns / thumb_* を大きくすると章名を読み取れる解像度になる。
    """
    url = CFURLCreateWithFileSystemPath(
        kCFAllocatorDefault, str(pdf_path), kCFURLPOSIXPathStyle, False
    )
    doc = Quartz.CGPDFDocumentCreateWithURL(url)
    if doc is None:
        raise RuntimeError(f"PDF を開けません: {pdf_path}")

    rows = (len(pages) + columns - 1) // columns
    width = columns * thumb_width
    height = max(1, rows) * thumb_height

    color_space = Quartz.CGColorSpaceCreateDeviceRGB()
    context = Quartz.CGBitmapContextCreate(
        None, width, height, 8, width * 4,
        color_space, Quartz.kCGImageAlphaPremultipliedFirst
    )
    if context is None:
        raise RuntimeError(f"シート画像の作成に失敗しました（{width}x{height}）")
    # 背景をグレーにしてページの境界を分かりやすくする
    Quartz.CGContextSetRGBFillColor(context, 0.85, 0.85, 0.85, 1.0)
    Quartz.CGContextFillRect(context, Quartz.CGRectMake(0, 0, width, height))

    for index, page_number in enumerate(pages):
        # ページ単位でキャンセルを拾う（1枚描き切るまで待たせない）
        if is_cancelled is not None and is_cancelled():
            raise SheetCancelled()
        column, row = index % columns, index // columns
        x = column * thumb_width
        y = height - (row + 1) * thumb_height

        page = Quartz.CGPDFDocumentGetPage(doc, page_number)
        if page is None:
            raise RuntimeError(f"ページ {page_number} を読み込めません: {pdf_path}")
        rect = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
        if rect.size.width <= 0 or rect.size.height <= 0:
            raise RuntimeError(f"ページ {page_number} のサイズが不正です: {pdf_path}")
        scale = min(
            (thumb_width - 6) / rect.size.width,
            (thumb_height - 6) / rect.size.height,
        )

        Quartz.CGContextSaveGState(context)
        Quartz.CGContextSetRGBFillColor(context, 1.0, 1.0, 1.0, 1.0)
        Quartz.CGContextFillRect(
            context,
            Quartz.CGRectMake(
                x + 3, y + 3, rect.size.width * scale, rect.size.height * scale
            ),
        )
        Quartz.CGContextTranslateCTM(context, x + 3, y + 3)
        Quartz.CGContextScaleCTM(context, scale, scale)
        Quartz.CGContextDrawPDFPage(context, page)
        Quartz.CGContextRestoreGState(context)

    image = Quartz.CGBitmapContextCreateImage(context)
    out_url = CFURLCreateWithFileSystemPath(
        kCFAllocatorDefault, str(out_path), kCFURLPOSIXPathStyle, False
    )
    destination = Quartz.CGImageDestinationCreateWithURL(out_url, "public.png", 1, None)
    if destination is None:
        raise RuntimeError(f"シート画像を書き出せません: {out_path}")
    Quartz.CGImageDestinationAddImage(destination, image, None)
    if not Quartz.CGImageDestinationFinalize(destination):
        raise RuntimeError(f"シート画像の書き出しに失敗しました: {out_path}")
    # 空ファイルのまま Claude に渡さないよう確認する
    if not Path(out_path).exists() or Path(out_path).stat().st_size == 0:
        raise RuntimeError(f"シート画像が空です: {out_path}")
    return str(out_path)
