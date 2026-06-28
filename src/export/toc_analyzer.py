"""目次画像から章境界を自動算出するロジックとエンジン"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


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


_PROMPT_TEMPLATE = (
    "次の画像は本の目次のページです: {paths}\n"
    "各画像を読み、章タイトルと、その章に書かれている印刷ページ番号を抽出してください。\n"
    "結果は説明を含めず、次の形式の JSON 配列だけを出力してください:\n"
    '[{{"name": "章タイトル", "page": 章の開始印刷ページ番号(整数)}}]'
)


def _extract_entries(stdout: str) -> list[TocEntry]:
    """claude の出力テキストから JSON 配列を取り出して TocEntry 列にする。"""
    text = stdout.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"目次の解析結果を読み取れませんでした: {stdout[:200]}")
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"目次の解析結果を読み取れませんでした: {stdout[:200]}"
            ) from exc

    entries: list[TocEntry] = []
    for item in data:
        entries.append(TocEntry(name=str(item["name"]), printed_page=int(item["page"])))
    return entries


class ClaudeTocEngine:
    """claude CLI をヘッドレス実行して目次を解析するエンジン"""

    def __init__(self, timeout: int = 120):
        self.timeout = timeout

    def analyze(self, image_paths: list[Path]) -> list[TocEntry]:
        paths = ", ".join(str(p) for p in image_paths)
        prompt = _PROMPT_TEMPLATE.format(paths=paths)
        result = subprocess.run(
            ["claude", "-p", "--output-format", "json", prompt],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"claude CLI が失敗しました: {detail[:200]}")
        # --output-format json は {"result": "<assistantのテキスト>"} を返す
        try:
            payload = json.loads(result.stdout)
            inner = payload.get("result", result.stdout)
        except json.JSONDecodeError:
            inner = result.stdout
        return _extract_entries(inner)
