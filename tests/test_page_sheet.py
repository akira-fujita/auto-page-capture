# tests/test_page_sheet.py
"""コンタクトシートのページ割りのテスト"""

from src.export.page_sheet import sheet_ranges


def test_sheet_ranges_splits_pages_into_sheets():
    """ページを1枚あたりの上限で区切る（1-indexed、端数も1枚に収める）"""
    assert sheet_ranges(10, per_sheet=4) == [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10]]


def test_build_contact_sheet_writes_png(tmp_path):
    """指定ページをサムネイル格子にしてPNGを書き出す"""
    import tempfile
    from pathlib import Path
    from pypdf import PdfWriter
    from src.export.page_sheet import build_contact_sheet

    pdf_path = tmp_path / "sample.pdf"
    writer = PdfWriter()
    for _ in range(5):
        writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as f:
        writer.write(f)

    out = tmp_path / "sheet.png"
    result = build_contact_sheet(pdf_path, [1, 2, 3, 4, 5], out)
    assert Path(result) == out
    assert out.exists() and out.stat().st_size > 0


def test_build_contact_sheet_accepts_layout_overrides(tmp_path):
    """列数とサムネイルサイズを指定できる（章名を読ませるための拡大用）"""
    from pathlib import Path
    from pypdf import PdfWriter
    from src.export.page_sheet import build_contact_sheet

    pdf_path = tmp_path / "sample.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as f:
        writer.write(f)

    out = tmp_path / "big.png"
    build_contact_sheet(
        pdf_path, [1, 2, 3], out, columns=2, thumb_width=600, thumb_height=800
    )
    assert out.exists()
    # 2列×2行 = 1200x1600 のはず
    from PyQt6.QtGui import QImage
    image = QImage(str(out))
    assert (image.width(), image.height()) == (1200, 1600)


def test_default_thumbnail_is_large_enough_to_read_chapter_layout():
    """既定のサムネイルは章扉レイアウトが判別できるサイズ（240x320以上）"""
    from src.export import page_sheet

    assert page_sheet.THUMB_WIDTH >= 240
    assert page_sheet.THUMB_HEIGHT >= 320
    # 1シートの高さが過大にならないよう列数と枚数を抑える
    assert page_sheet.COLUMNS <= 6


def test_build_contact_sheet_rejects_unreadable_pdf(tmp_path):
    """読めないPDFは明確なエラーにする（壊れた画像でClaudeを呼ばない）"""
    import pytest
    from src.export.page_sheet import build_contact_sheet

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    with pytest.raises(RuntimeError, match="PDF を開けません"):
        build_contact_sheet(broken, [1], tmp_path / "out.png")


def test_build_contact_sheet_rejects_out_of_range_page(tmp_path):
    """存在しないページ番号は明確なエラーにする"""
    import pytest
    from pypdf import PdfWriter
    from src.export.page_sheet import build_contact_sheet

    pdf_path = tmp_path / "sample.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as f:
        writer.write(f)

    with pytest.raises(RuntimeError, match="ページ"):
        build_contact_sheet(pdf_path, [5], tmp_path / "out.png")


def test_sheet_ranges_edge_cases():
    """ページ0枚は空、per_sheet が0以下なら明確なエラー"""
    import pytest
    from src.export.page_sheet import sheet_ranges

    assert sheet_ranges(0, per_sheet=10) == []
    with pytest.raises(ValueError, match="per_sheet"):
        sheet_ranges(10, per_sheet=0)
    with pytest.raises(ValueError, match="per_sheet"):
        sheet_ranges(10, per_sheet=-3)


def test_build_contact_sheet_stops_when_cancelled(tmp_path):
    """描画中でもページ単位でキャンセルできる（GUIを長く待たせない）"""
    import pytest
    from pypdf import PdfWriter
    from src.export.page_sheet import build_contact_sheet, SheetCancelled

    pdf_path = tmp_path / "sample.pdf"
    writer = PdfWriter()
    for _ in range(20):
        writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as f:
        writer.write(f)

    drawn = []

    def cancel_after_three():
        drawn.append(1)
        return len(drawn) > 3

    with pytest.raises(SheetCancelled):
        build_contact_sheet(
            pdf_path, list(range(1, 21)), tmp_path / "out.png",
            is_cancelled=cancel_after_three,
        )
    assert len(drawn) <= 5, "キャンセル後すぐ止まる"
