"""目次画像から章境界を自動算出するロジックとエンジン"""

from dataclasses import dataclass


@dataclass
class TocEntry:
    """目次から抽出した1章ぶんの情報"""
    name: str
    printed_page: int


@dataclass
class ChapterRange:
    """算出された章の範囲。start/end は0始まり包含(Chapterと同形)"""
    name: str
    start: int
    end: int


def compute_offset(anchor_capture_no: int, anchor_printed_page: int) -> int:
    """印刷ページ番号→キャプチャ枚数のズレ(offset)を求める。

    capture_no(1始まり) = printed_page + offset
    """
    return anchor_capture_no - anchor_printed_page


def entries_to_chapters(
    entries: list[TocEntry], offset: int, total_pages: int
) -> tuple[list[ChapterRange], list[str]]:
    """目次エントリを章範囲へ変換する。

    - printed_page を0始まりキャプチャindexへ変換: start = printed_page + offset - 1
    - 範囲外(<0 または >=total_pages)は除外し警告
    - start でソートし、end = 次章start-1、最終章は total_pages-1
    - 同一 start の重複は先勝ちで除外し警告
    """
    warnings: list[str] = []
    converted: list[tuple[int, str]] = []
    for e in entries:
        start = e.printed_page + offset - 1
        if start < 0 or start >= total_pages:
            warnings.append(
                f"「{e.name}」(印刷p.{e.printed_page}) → 範囲外のため除外しました"
            )
            continue
        converted.append((start, e.name))

    converted.sort(key=lambda t: t[0])

    chapters: list[ChapterRange] = []
    seen_starts: set[int] = set()
    deduped: list[tuple[int, str]] = []
    for start, name in converted:
        if start in seen_starts:
            warnings.append(f"「{name}」→ 開始ページが重複するため除外しました")
            continue
        seen_starts.add(start)
        deduped.append((start, name))

    for i, (start, name) in enumerate(deduped):
        if i < len(deduped) - 1:
            end = deduped[i + 1][0] - 1
        else:
            end = total_pages - 1
        chapters.append(ChapterRange(name=name, start=start, end=end))

    return chapters, warnings
