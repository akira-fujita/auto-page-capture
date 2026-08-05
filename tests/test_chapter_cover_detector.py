# tests/test_claude_detector.py
"""claude CLI 経由の画像章検出のテスト"""

import pytest

from src.export.chapter_cover_detector import parse_chapters_json


def test_parses_valid_json():
    """章名と物理ページを (name, page) のリストにする"""
    out = '{"chapters":[{"page":15,"label":"序章 この本の考え方"},{"page":35,"label":"第1章 イシュードリブン"}]}'
    assert parse_chapters_json(out, page_count=211) == [
        ("序章 この本の考え方", 15),
        ("第1章 イシュードリブン", 35),
    ]


def test_extracts_json_surrounded_by_prose():
    """前後に説明文やコードフェンスが付いていても JSON を取り出す"""
    out = (
        "画像を確認しました。\n```json\n"
        '{"chapters":[{"page":15,"label":"序章"}]}\n'
        "```\n以上です。"
    )
    assert parse_chapters_json(out, page_count=211) == [("序章", 15)]


def test_validates_pages():
    """範囲外・重複ページを破棄し、ページ順に並べ替える"""
    out = (
        '{"chapters":['
        '{"page":35,"label":"第1章"},'
        '{"page":15,"label":"序章"},'
        '{"page":35,"label":"重複"},'
        '{"page":0,"label":"範囲外(下)"},'
        '{"page":999,"label":"範囲外(上)"}'
        "]}"
    )
    assert parse_chapters_json(out, page_count=211) == [("序章", 15), ("第1章", 35)]


def test_detect_merges_results_from_all_sheets(tmp_path):
    """全シートの結果をページ順にマージして返す"""
    from src.export.chapter_cover_detector import detect_chapters_from_images

    calls = []

    def fake_runner(prompt: str, image_path: str) -> str:
        calls.append((prompt, image_path))
        if "1-56" in image_path:
            return '{"chapters":[{"page":15,"label":"序章"},{"page":35,"label":"第1章"}]}'
        return '{"chapters":[{"page":79,"label":"第2章"}]}'

    def fake_sheet_builder(pages, out_path):
        # 実際の描画はせずパスだけ返す
        return f"{out_path}"

    chapters = detect_chapters_from_images(
        page_count=112,
        output_dir=str(tmp_path),
        runner=fake_runner,
        sheet_builder=fake_sheet_builder,
        per_sheet=56,
    )
    assert chapters == [("序章", 15), ("第1章", 35), ("第2章", 79)]
    assert len(calls) == 2, "シート枚数分だけ呼ばれる"


def test_run_claude_cli_invokes_expected_command(monkeypatch):
    """画像のあるディレクトリを cwd にして、ベース名で claude を呼ぶ

    ヘッドレスの claude は cwd 配下のファイルしか追加許可なしに Read できない
    （main の ClaudeTocEngine が同じ制約に対処している）。
    """
    import subprocess
    from src.export.chapter_cover_detector import run_claude_cli

    captured = {}

    class FakeProc:
        returncode = 0

        def communicate(self, timeout=None):
            return ('{"result": "{\\"chapters\\":[]}"}', "")

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    out = run_claude_cli("プロンプト sheet.png", "/tmp/sheets/sheet.png")
    assert out == '{"chapters":[]}', "--output-format json の result を取り出す"
    cmd = captured["cmd"]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert captured["kwargs"].get("cwd") == "/tmp/sheets"


def test_run_claude_cli_reports_missing_binary(monkeypatch):
    """claude CLI が無い場合は原因が分かる例外を投げる"""
    import subprocess
    from src.export.chapter_cover_detector import run_claude_cli

    def fake_popen(cmd, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError, match="claude CLI が見つかりません"):
        run_claude_cli("プロンプト", "/tmp/sheet.png")


def test_refine_chapter_names_replaces_labels(tmp_path):
    """2パス目で章扉ページを拡大して章名を書き写し、ラベルを置き換える"""
    from src.export.chapter_cover_detector import refine_chapter_names

    def fake_runner(prompt, image_path):
        return (
            '{"titles":['
            '{"page":15,"label":"序章 この本の考え方","is_chapter_start":true},'
            '{"page":35,"label":"第1章 イシュードリブン","is_chapter_start":true},'
            '{"page":79,"label":"第2章 仮説ドリブン①","is_chapter_start":true}]}'
        )

    def fake_sheet_builder(pages, out_path):
        return out_path

    refined = refine_chapter_names(
        [("序章", 15), ("第3章 章扉", 79), ("第1章", 35)],
        output_dir=str(tmp_path),
        runner=fake_runner,
        sheet_builder=fake_sheet_builder,
    )
    assert refined == [
        ("序章 この本の考え方", 15),
        ("第1章 イシュードリブン", 35),
        ("第2章 仮説ドリブン①", 79),
    ]


def test_refine_drops_pages_that_are_not_chapter_starts(tmp_path):
    """2パス目で章扉でないと判定されたページは捨てる"""
    from src.export.chapter_cover_detector import refine_chapter_names

    def fake_runner(prompt, image_path):
        return (
            '{"titles":['
            '{"page":15,"label":"序章 この本の考え方","is_chapter_start":true},'
            '{"page":136,"label":"","is_chapter_start":false}'
            "]}"
        )

    refined = refine_chapter_names(
        [("序章", 15), ("第4章", 136)],
        output_dir=str(tmp_path),
        runner=fake_runner,
        sheet_builder=lambda pages, out_path: out_path,
    )
    assert refined == [("序章 この本の考え方", 15)]


def test_refine_requires_explicit_verification(tmp_path):
    """is_chapter_start が true でないページは採用しない（欠落・null・文字列も不採用）"""
    from src.export.chapter_cover_detector import refine_chapter_names

    def fake_runner(prompt, image_path):
        return (
            '{"titles":['
            '{"page":15,"label":"序章","is_chapter_start":true},'
            '{"page":35,"label":"第1章"},'
            '{"page":79,"label":"第2章","is_chapter_start":null},'
            '{"page":106,"label":"第3章","is_chapter_start":"yes"}'
            "]}"
        )

    refined = refine_chapter_names(
        [("A", 15), ("B", 35), ("C", 79), ("D", 106)],
        output_dir=str(tmp_path),
        runner=fake_runner,
        sheet_builder=lambda pages, out_path: out_path,
    )
    assert refined == [("序章", 15)]


def test_timeout_is_converted_to_friendly_error(monkeypatch):
    """タイムアウトは Python の生の例外ではなく理由の分かるエラーにする"""
    import subprocess
    from src.export.chapter_cover_detector import run_claude_cli

    class NeverFinishes:
        returncode = None

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired("claude", timeout or 1)

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            pass

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: NeverFinishes())
    with pytest.raises(RuntimeError, match="時間内に応答しませんでした"):
        run_claude_cli("プロンプト", "/tmp/sheet.png", timeout=2)


def test_detect_reports_which_sheet_failed(tmp_path):
    """途中のシートで失敗したら、どのページ範囲で失敗したか分かる"""
    from src.export.chapter_cover_detector import detect_chapters_from_images

    def fake_runner(prompt, image_path):
        raise RuntimeError("claude CLI が時間内に応答しませんでした")

    with pytest.raises(RuntimeError, match="p.1-36"):
        detect_chapters_from_images(
            page_count=40,
            output_dir=str(tmp_path),
            runner=fake_runner,
            sheet_builder=lambda pages, out_path: out_path,
        )


def test_prompts_reference_image_by_basename():
    """プロンプトはベース名で画像を参照する（cwd 配下しか読めない制約に合わせる）"""
    from src.export.chapter_cover_detector import build_prompt, build_title_prompt

    p1 = build_prompt([1, 2, 3], "/var/folders/xyz/sheets/sheet_1-36.png")
    p2 = build_title_prompt([15, 35], "/var/folders/xyz/sheets/titles_15-35.png")
    for prompt, base in ((p1, "sheet_1-36.png"), (p2, "titles_15-35.png")):
        assert base in prompt
        assert "/var/folders" not in prompt, "絶対パスを渡さない"


def test_run_claude_cli_can_be_cancelled(monkeypatch):
    """キャンセル要求で実行中の claude プロセスを終了させる"""
    import subprocess
    from src.export.chapter_cover_detector import run_claude_cli

    terminated = []

    class FakeProc:
        def __init__(self):
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("claude", timeout or 1)
            return ('{"result": "{}"}', "")

        def terminate(self):
            terminated.append(True)

        def kill(self):
            terminated.append("kill")

        @property
        def returncode(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: FakeProc())

    cancelled = {"value": True}
    with pytest.raises(RuntimeError, match="キャンセル"):
        run_claude_cli(
            "プロンプト", "/tmp/sheets/sheet.png",
            is_cancelled=lambda: cancelled["value"],
        )
    assert terminated, "実行中のプロセスを終了させる"


def test_kill_path_reaps_process(monkeypatch):
    """SIGTERM に応じないプロセスは kill 後に回収まで行う（ゾンビを残さない）"""
    import subprocess
    from src.export.chapter_cover_detector import run_claude_cli

    events = []

    class StubbornProc:
        returncode = None

        def communicate(self, timeout=None):
            events.append(("communicate", timeout))
            raise subprocess.TimeoutExpired("claude", timeout or 1)

        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("kill")

        def wait(self, timeout=None):
            events.append("wait")

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: StubbornProc())
    with pytest.raises(RuntimeError, match="キャンセル"):
        run_claude_cli("プロンプト", "/tmp/sheets/s.png", is_cancelled=lambda: True)

    assert "terminate" in events and "kill" in events
    assert events[-1] == "wait", "kill 後にプロセスを回収する"


def test_timeout_uses_monotonic_deadline(monkeypatch):
    """短いタイムアウトでも要求時間を大きく超えない"""
    import subprocess
    import time
    from src.export.chapter_cover_detector import run_claude_cli

    class NeverFinishes:
        returncode = None

        def communicate(self, timeout=None):
            time.sleep(min(timeout or 0.05, 0.05))
            raise subprocess.TimeoutExpired("claude", timeout or 1)

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            pass

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: NeverFinishes())
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="時間内に応答しませんでした"):
        run_claude_cli("プロンプト", "/tmp/sheets/s.png", timeout=0.2)
    assert time.monotonic() - started < 1.5
