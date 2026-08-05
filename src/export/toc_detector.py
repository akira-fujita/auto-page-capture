# src/export/toc_detector.py
"""目次ページ・本文見出しから章の開始ページを検出する（PDF非依存の純ロジック）

入力はページごとのテキスト（`list[str]`、index 0 が p.1）。
出力の開始ページは必ず PDF の物理ページ番号（1-indexed）。
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

# 見出しとみなす行の最大長（本文の文章を弾くため）
MAX_HEADING_LEN = 40
# 目次ページを探す範囲（先頭からのページ数）
_TOC_SEARCH_PAGES = 30

_JP_CHAPTER_RE = re.compile(r"^第\s*([0-9]+|[一二三四五六七八九十]+)\s*章")
_EN_CHAPTER_RE = re.compile(r"^chapter\s+([0-9]+)\b", re.IGNORECASE)

_TOC_TITLES = ("目次", "もくじ", "contents", "table of contents", "contents 目次")

# 目次エントリ（リーダー＋末尾のページ番号）
_TOC_ENTRY_RE = re.compile(r"^(?P<title>.+?)[\s.．・·…‥\-]{2,}(?P<page>[0-9]+)$")


@dataclass(frozen=True)
class TextDetectionResult:
    """テキストからの章検出結果

    chapters: (章名, 物理ページ 1-indexed) のリスト
    source: "heading"=本文見出しの実測 / "toc"=目次の印字ページ番号 / "none"=検出なし
    """

    chapters: list[tuple[str, int]]
    source: Literal["heading", "toc", "none"]


def has_text_layer(page_texts: list[str]) -> bool:
    """テキスト層を持つ PDF かどうか（スキャン画像のみの PDF を除外する）"""
    total = sum(len("".join(text.split())) for text in page_texts)
    return total >= 100


def _normalize(text: str) -> str:
    """全角数字・全角空白を半角化する"""
    return unicodedata.normalize("NFKC", text)


def _is_heading_line(line: str) -> bool:
    """見出しらしい行かどうか（本文中の言及を弾く）"""
    if len(line) > MAX_HEADING_LEN:
        return False
    return "。" not in line and "、" not in line


def _parse_number(token: str) -> int | None:
    """アラビア数字または漢数字（一〜十九）を int に変換"""
    kanji = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    if token.isdigit():
        return int(token)
    if token == "十":
        return 10
    if token.startswith("十"):
        rest = kanji.get(token[1:])
        return 10 + rest if rest else None
    return kanji.get(token)


def _chapter_number(line: str) -> int | None:
    """行頭の章番号を返す。章見出しでなければ None"""
    m = _JP_CHAPTER_RE.match(line) or _EN_CHAPTER_RE.match(line)
    if m is None:
        return None
    # 「第10章を参照」のように直後がひらがな（助詞・活用）なら見出しではなく本文
    rest = line[m.end():]
    if rest and "぀" <= rest[0] <= "ゟ":
        return None
    return _parse_number(m.group(1))


def _parse_toc_entries(text: str) -> list[tuple[str, int]]:
    """目次ページから (タイトル, 印字ページ番号) を抽出する"""
    entries: list[tuple[str, int]] = []
    for raw_line in _normalize(text).splitlines():
        line = raw_line.strip()
        m = _TOC_ENTRY_RE.match(line) if line else None
        if m is None:
            continue
        title = m.group("title").strip(" .．・·…‥-")
        if title:
            entries.append((title, int(m.group("page"))))
    return entries


def _find_toc_pages(page_texts: list[str]) -> set[int]:
    """目次ページのインデックス集合を返す

    起点はページ先頭付近に「目次」等の短い見出し行を持つページ。
    そこから連続してエントリ行を2行以上持つページも目次の続きとみなす。
    """
    toc_pages: set[int] = set()
    for index in range(min(len(page_texts), _TOC_SEARCH_PAGES)):
        text = page_texts[index]
        if index in toc_pages or not _looks_like_toc_page(text):
            continue
        toc_pages.add(index)
        # 続きのページ: エントリ行が2行以上あれば継続。
        # 最終ページはエントリ1行だけのこともあるので、その1ページ分も取り込む。
        follower = index + 1
        while follower < len(page_texts):
            entries = len(_parse_toc_entries(page_texts[follower]))
            if entries >= 2:
                toc_pages.add(follower)
                follower += 1
                continue
            if entries == 1 and follower - 1 in toc_pages and follower - 1 != index:
                toc_pages.add(follower)
            break
    return toc_pages


def _parse_toc(
    page_texts: list[str], toc_pages: set[int]
) -> dict[int, tuple[str, int]]:
    """目次の章エントリを {章番号: (タイトル, 印字ページ)} で返す"""
    entries: dict[int, tuple[str, int]] = {}
    for index in sorted(toc_pages):
        for title, printed in _parse_toc_entries(page_texts[index]):
            number = _chapter_number(title)
            if number is None or number in entries:
                continue
            entries[number] = (title, printed)
    return entries


def _looks_like_toc_page(text: str) -> bool:
    """目次ページかどうか（ページ先頭付近に目次見出しがあるか）"""
    lines = [line.strip() for line in _normalize(text).splitlines() if line.strip()]
    for line in lines[:5]:
        # 「目次」等が単独の見出し行として置かれているページだけを目次とみなす
        # （本文中に contents の語があるだけのページを弾く）
        if line.lower().strip(" 　:：-—・") in _TOC_TITLES:
            return True
    return False


def _scan_body_headings(page_texts: list[str], skip: set[int]) -> dict[int, tuple[int, str]]:
    """本文から章見出しを検出し {章番号: (物理ページ, 見出し行)} を返す

    各章番号について最初に出現したページを採用する（柱＝実行ヘッダは
    章の初出ページから始まるため、初出採用で正しい結果になる）。
    """
    headings: dict[int, tuple[int, str]] = {}
    for index, text in enumerate(page_texts):
        if index in skip:
            continue
        for raw_line in _normalize(text).splitlines():
            line = raw_line.strip()
            if not line or not _is_heading_line(line):
                continue
            number = _chapter_number(line)
            if number is None or number in headings:
                continue
            headings[number] = (index + 1, line)
    return headings


def detect_chapters_from_text(page_texts: list[str]) -> TextDetectionResult:
    """ページテキストから章の開始ページを検出する"""
    toc_pages = _find_toc_pages(page_texts)
    headings = _scan_body_headings(page_texts, skip=toc_pages)
    toc_entries = _parse_toc(page_texts, toc_pages)
    if not headings:
        # 本文見出しが取れない場合は目次の印字ページ番号で代替する
        # （物理ページとズレ得るため、UI 側で確認を促す）
        printed = sorted(
            (page, number, title) for number, (title, page) in toc_entries.items()
        )
        chapters = _enforce_invariants(
            [(page, number, title) for page, number, title in printed
             if 1 <= page <= len(page_texts)]
        )
        if chapters:
            return TextDetectionResult(chapters, "toc")
        return TextDetectionResult([], "none")
    candidates = sorted(
        (page, number, toc_entries.get(number, (None, None))[0] or line)
        for number, (page, line) in headings.items()
    )
    return TextDetectionResult(_enforce_invariants(candidates), "heading")


def _enforce_invariants(
    candidates: list[tuple[int, int, str]]
) -> list[tuple[str, int]]:
    """ページ順に走査し、章番号が増加しないエントリを破棄する

    ページを送るにつれ章番号は増えるはずなので、それを崩す候補（誤検出）は捨てる。
    間違ったページを出すより出さない方針。
    """
    # ページ順に並べた候補から、章番号とページがともに厳密増加する最長列を選ぶ。
    # 貪欲に先頭から採ると、前方に紛れた外れ値（例: 前付けの「第10章 付録」）1件で
    # 以降の本物の章が全滅するため、最長列を採用する。
    best_length = [1] * len(candidates)
    previous = [-1] * len(candidates)
    for i, (page_i, number_i, _) in enumerate(candidates):
        for j in range(i):
            page_j, number_j, _ = candidates[j]
            if number_j < number_i and page_j < page_i and best_length[j] + 1 > best_length[i]:
                best_length[i] = best_length[j] + 1
                previous[i] = j

    if not candidates:
        return []

    # 同じ長さなら先に現れる列を選ぶ（max は最初の最大値を返す）
    end = max(range(len(candidates)), key=lambda i: (best_length[i], -i))
    indices = []
    while end != -1:
        indices.append(end)
        end = previous[end]
    indices.reverse()

    return [(candidates[i][2], candidates[i][0]) for i in indices]
