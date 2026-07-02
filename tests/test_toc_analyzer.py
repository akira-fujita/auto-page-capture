import json
import subprocess
from pathlib import Path

import pytest

from src.export.toc_analyzer import (
    TocEntry, ChapterRange, compute_offset, entries_to_chapters,
    _extract_entries, _parse_page, ClaudeTocEngine,
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


def test_extract_entries_plain_json():
    out = '[{"name": "第1章", "page": 1}, {"name": "第2章", "page": 45}]'
    entries = _extract_entries(out)
    assert entries == [TocEntry("第1章", 1), TocEntry("第2章", 45)]


def test_extract_entries_with_codeblock_and_prose():
    out = "解析しました:\n```json\n[{\"name\": \"序章\", \"page\": 3}]\n```\nどうぞ"
    entries = _extract_entries(out)
    assert entries == [TocEntry("序章", 3)]


def test_extract_entries_raises_on_garbage():
    with pytest.raises(ValueError):
        _extract_entries("ページ番号が読めませんでした")


def test_extract_entries_roman_page_marked_front_matter():
    """ローマ数字ページ(前付け)は printed_page=None かつ roman_page に原文を保持"""
    out = '[{"name": "もう一度、世界を変えよう", "page": "vii"}]'
    entries = _extract_entries(out)
    assert entries == [TocEntry("もう一度、世界を変えよう", None, "vii")]


@pytest.mark.parametrize("raw,expected", [
    (7, (7, None)),
    ("7", (7, None)),
    ("007", (7, None)),
    ("vii", (None, "vii")),
    ("xiv", (None, "xiv")),
    ("VII", (None, "VII")),
    ("iv", (None, "iv")),
    ("i", (None, "i")),
    ("xl", (None, "xl")),
])
def test_parse_page_valid(raw, expected):
    assert _parse_page(raw) == expected


@pytest.mark.parametrize("raw", ["iiii", "vx", "civil", "", "   ", "7a", "7-8", "vv"])
def test_parse_page_invalid_raises(raw):
    """無効なローマ数字並び・非数値は前付け誤認せず ValueError"""
    with pytest.raises(ValueError):
        _parse_page(raw)


def test_parse_page_bool_rejected():
    with pytest.raises(ValueError):
        _parse_page(True)


def test_extract_entries_arabic_string_page_becomes_int():
    """アラビア数字が文字列で来ても int に正規化する"""
    out = '[{"name": "第1章", "page": "7"}]'
    entries = _extract_entries(out)
    assert entries == [TocEntry("第1章", 7)]


def test_entries_to_chapters_excludes_front_matter_with_warning():
    entries = [
        TocEntry("序文", None, "vii"),
        TocEntry("第1章", 1),
    ]
    chapters, warnings = entries_to_chapters(entries, offset=7, total_pages=60)
    assert [c.name for c in chapters] == ["第1章"]
    assert len(warnings) == 1
    assert "序文" in warnings[0]


def test_entries_to_chapters_front_matter_does_not_evict_body_chapter():
    """回帰: 前付け(vii→7誤読相当)が本文2章(p.7)を重複除外で押し出さない"""
    entries = [
        TocEntry("もう一度、世界を変えよう", None, "vii"),  # 前付け
        TocEntry("1章", 1),
        TocEntry("2章 今すぐ減量を", 7),  # 本文。前付けvii と同ページ空間で衝突していた
        TocEntry("3章", 25),
    ]
    chapters, _ = entries_to_chapters(entries, offset=16, total_pages=200)
    names = [c.name for c in chapters]
    assert "2章 今すぐ減量を" in names
    assert "もう一度、世界を変えよう" not in names
    # 2章 の start は印刷p.7 → 7+16-1 = 22, end は 3章start-1 = (25+16-1)-1 = 39
    ch2 = next(c for c in chapters if c.name == "2章 今すぐ減量を")
    assert (ch2.start, ch2.end) == (22, 39)


def test_claude_engine_invokes_cli_and_parses(monkeypatch):
    captured = {}

    class _Result:
        stdout = json.dumps({"result": '[{"name": "第1章", "page": 1}]'})
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _Result()

    monkeypatch.setattr("src.export.toc_analyzer.subprocess.run", fake_run)
    engine = ClaudeTocEngine()
    entries = engine.analyze([Path("/tmp/toc1.png"), Path("/tmp/toc2.png")])

    assert entries == [TocEntry("第1章", 1)]
    assert captured["cmd"][0] == "claude"
    # 画像パスがプロンプトに含まれる
    joined = " ".join(captured["cmd"])
    assert "toc1.png" in joined and "toc2.png" in joined


def test_claude_engine_runs_in_image_dir_with_basenames(monkeypatch):
    """権限対策: cwd=画像ディレクトリ、ベース名参照、stdin は閉じる。

    絶対パス(cwd外)だと claude が Read 権限で弾かれるため、画像の親を
    cwd にして相対のベース名で渡す。
    """
    captured = {}

    class _Result:
        stdout = json.dumps({"result": '[{"name": "第1章", "page": 1}]'})
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr("src.export.toc_analyzer.subprocess.run", fake_run)
    p1 = Path("/var/folders/xx/T/tmpABC/toc_12.png")
    p2 = Path("/var/folders/xx/T/tmpABC/toc_13.png")
    ClaudeTocEngine().analyze([p1, p2])

    # cwd は resolve() 済みの画像ディレクトリ（symlink 正規化を考慮）
    assert captured["kwargs"].get("cwd") == str(p1.resolve().parent)
    assert captured["kwargs"].get("stdin") == subprocess.DEVNULL
    joined = " ".join(captured["cmd"])
    # 絶対パスではなくベース名で渡っている
    assert "toc_12.png" in joined and "toc_13.png" in joined
    assert str(p1.resolve()) not in joined
    # --allowedTools は使わない(可変長引数がプロンプトを食うため)
    assert "--allowedTools" not in captured["cmd"]


def test_claude_engine_empty_list_returns_empty():
    assert ClaudeTocEngine().analyze([]) == []


def test_claude_engine_mixed_directories_raises(monkeypatch):
    """別ディレクトリの画像が混在したら明示的に失敗（静かな0件を防ぐ）"""
    monkeypatch.setattr(
        "src.export.toc_analyzer.subprocess.run",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    with pytest.raises(RuntimeError):
        ClaudeTocEngine().analyze([Path("/tmp/dirA/a.png"), Path("/tmp/dirB/b.png")])


def test_claude_engine_raises_on_nonzero_returncode(monkeypatch):
    class _FailResult:
        returncode = 1
        stderr = "boom"
        stdout = ""

    monkeypatch.setattr(
        "src.export.toc_analyzer.subprocess.run", lambda *a, **kw: _FailResult()
    )
    with pytest.raises(RuntimeError):
        ClaudeTocEngine().analyze([Path("/tmp/x.png")])


def test_claude_engine_bare_json_array_outer_payload(monkeypatch):
    """FIX 2: outer payload が dict でない(bare JSON array)場合、AttributeError を起こさずエントリを返す"""
    class _BareArrayResult:
        returncode = 0
        stderr = ""
        stdout = '[{"name": "第1章", "page": 1}]'

    monkeypatch.setattr(
        "src.export.toc_analyzer.subprocess.run", lambda *a, **kw: _BareArrayResult()
    )
    entries = ClaudeTocEngine().analyze([Path("/tmp/x.png")])
    assert entries == [TocEntry("第1章", 1)]
