from src.export.toc_analyzer import (
    TocEntry, ChapterRange, compute_offset, entries_to_chapters,
)


def test_compute_offset():
    # 印刷p.1 がキャプチャ#8 → offset = 7
    assert compute_offset(8, 1) == 7


def test_entries_to_chapters_basic_offset_and_ranges():
    entries = [
        TocEntry("第1章", 1),
        TocEntry("第2章", 45),
    ]
    # offset 7, 全12+ページ想定で total_pages=60
    chapters, warnings = entries_to_chapters(entries, offset=7, total_pages=60)
    assert warnings == []
    # 第1章: start = 1+7-1 = 7(0始まり, 表示p.8), end = 次章start-1 = 50
    # 第2章: start = 45+7-1 = 51, end = total-1 = 59
    assert chapters == [
        ChapterRange("第1章", 7, 50),
        ChapterRange("第2章", 51, 59),
    ]


def test_entries_to_chapters_sorts_by_page():
    entries = [TocEntry("第2章", 45), TocEntry("第1章", 1)]
    chapters, _ = entries_to_chapters(entries, offset=7, total_pages=60)
    assert [c.name for c in chapters] == ["第1章", "第2章"]


def test_entries_to_chapters_excludes_out_of_range_with_warning():
    entries = [TocEntry("第1章", 1), TocEntry("付録", 320)]
    chapters, warnings = entries_to_chapters(entries, offset=7, total_pages=60)
    assert [c.name for c in chapters] == ["第1章"]
    assert len(warnings) == 1
    assert "付録" in warnings[0]


def test_entries_to_chapters_dedups_same_start_with_warning():
    entries = [TocEntry("第1章", 1), TocEntry("重複章", 1)]
    chapters, warnings = entries_to_chapters(entries, offset=7, total_pages=60)
    assert [c.name for c in chapters] == ["第1章"]
    assert len(warnings) == 1
