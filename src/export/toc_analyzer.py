"""目次画像から章境界を自動算出するロジックとエンジン"""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


# 妥当なローマ数字のみを前付けページとして検出する。
# 先頭の (?=...) で空文字を除外し、"iiii"/"vx"/"civil" 等の不正な並びは弾く。
_ROMAN_RE = re.compile(
    r"^(?=[ivxlcdm])m{0,4}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$",
    re.IGNORECASE,
)


@dataclass
class TocEntry:
    """目次から抽出した1章ぶんの情報

    printed_page はアラビア数字の本文ページ(整数)。前付けのようにページ番号が
    ローマ数字の場合は printed_page=None とし、roman_page に原文表記を保持する。
    """
    name: str
    printed_page: int | None
    roman_page: str | None = None


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
        if e.printed_page is None:
            page_label = e.roman_page or "ローマ数字"
            warnings.append(
                f"「{e.name}」(印刷p.{page_label}) → 前付けのため除外しました"
            )
            continue
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
    "各画像を読み、最上位の見出し（章・部・および前付け/巻末の独立項目）と、"
    "その開始印刷ページ番号を抽出してください。\n"
    "抽出する: 「N章」「第N部」などの章・部見出し、および"
    "はじめに/序文/参考文献/訳者あとがき/索引などの独立した項目。\n"
    "抽出しない: 各章の内側にある小見出し（例: 「プラクティスN」や節番号）は"
    "章の一部なので列挙しないでください。\n"
    "ページ番号がローマ数字(例: vii, xiv)の前付けページは、そのローマ数字を"
    "文字列のまま返してください。アラビア数字の本文ページは整数で返してください。"
    "ローマ数字を勝手にアラビア数字へ変換しないでください。\n"
    "結果は説明を含めず、次の形式の JSON 配列だけを出力してください:\n"
    '[{{"name": "章タイトル", "page": "vii" または 7}}]'
)


def _parse_page(raw) -> tuple[int | None, str | None]:
    """ページ番号の生値を (printed_page, roman_page) に正規化する。

    - int またはアラビア数字文字列 → (int, None)
    - ローマ数字文字列(vii 等) → (None, 原文) ※前付け扱い
    """
    if isinstance(raw, bool):  # bool は int のサブクラスなので先に弾く
        raise ValueError(f"ページ番号として不正です: {raw!r}")
    if isinstance(raw, int):
        return raw, None
    s = str(raw).strip()
    if _ROMAN_RE.fullmatch(s):
        return None, s
    return int(s), None


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
        printed_page, roman_page = _parse_page(item["page"])
        entries.append(
            TocEntry(name=str(item["name"]), printed_page=printed_page, roman_page=roman_page)
        )
    return entries


class ClaudeTocEngine:
    """claude CLI をヘッドレス実行して目次を解析するエンジン"""

    def __init__(self, timeout: int = 120):
        self.timeout = timeout

    def analyze(self, image_paths: list[Path]) -> list[TocEntry]:
        if not image_paths:
            return []
        # ヘッドレスの claude はワーキングディレクトリ配下のファイルしか
        # 追加許可なしで Read できない。画像の親を cwd にして相対のベース名で
        # 渡すことで /var/folders 等の一時パスでも読めるようにする。
        # symlink 表記の揺れを吸収するため resolve() で正規化し、
        # 全画像が同一ディレクトリにあることを要求する（別ディレクトリを
        # 絶対パスで渡すと再び権限で弾かれ静かに0件になるため明示的に失敗させる）。
        normalized = [p.resolve() for p in image_paths]
        parents = {p.parent for p in normalized}
        if len(parents) != 1:
            raise RuntimeError(
                "目次画像は同一ディレクトリに揃える必要があります（claude 解析の制約）"
            )
        workdir = normalized[0].parent
        refs = [p.name for p in normalized]
        prompt = _PROMPT_TEMPLATE.format(paths=", ".join(refs))
        result = subprocess.run(
            ["claude", "-p", "--output-format", "json", prompt],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            cwd=str(workdir),
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"claude CLI が失敗しました: {detail[:200]}")
        # --output-format json は {"result": "<assistantのテキスト>"} を返す
        try:
            payload = json.loads(result.stdout)
            if isinstance(payload, dict):
                inner = payload.get("result", result.stdout)
            else:
                inner = result.stdout
        except json.JSONDecodeError:
            inner = result.stdout
        return _extract_entries(inner)
