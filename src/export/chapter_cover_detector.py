# src/export/claude_detector.py
"""ページ画像から章扉を検出する（ローカルの claude CLI 経由）

テキスト層を持たない PDF（スキャン・画面キャプチャ）向け。
ページ画像を外部（Claude）に渡すため、呼び出し側で必ずユーザーの確認を取る。
"""

import json
import subprocess
import time
from pathlib import Path
from typing import Callable

from src.export.page_sheet import sheet_ranges

PER_SHEET = 36  # 6列×6行
# 章名の読み取りは拡大表示が必要なので1枚あたりの枚数を絞る
REFINE_PER_SHEET = 6
TIMEOUT_SECONDS = 300
# キャンセル要求を拾う間隔（秒）
_POLL_SECONDS = 1.0
# terminate 後に終了を待つ猶予（秒）
_TERMINATE_GRACE_SECONDS = 5


def detect_chapters_from_images(
    page_count: int,
    output_dir: str,
    runner: Callable[[str, str], str],
    sheet_builder: Callable[[list[int], str], str],
    per_sheet: int = PER_SHEET,
) -> list[tuple[str, int]]:
    """コンタクトシートを作り、1枚ずつ runner に渡して章扉を集める

    Args:
        page_count: PDFのページ数
        output_dir: シート画像の保存先
        runner: (プロンプト, 画像パス) -> claude の標準出力
        sheet_builder: (ページ番号リスト, 出力パス) -> 実際に書き出したパス
        per_sheet: 1枚のシートに載せるページ数
    """
    chapters: list[tuple[str, int]] = []
    for pages in sheet_ranges(page_count, per_sheet):
        out_path = f"{output_dir}/sheet_{pages[0]}-{pages[-1]}.png"
        try:
            image_path = sheet_builder(pages, out_path)
            stdout = runner(build_prompt(pages, image_path), image_path)
            chapters.extend(parse_chapters_json(stdout, page_count))
        except Exception as e:
            # どのページ範囲で失敗したかを添えて上げる（再実行の判断材料になる）
            raise RuntimeError(
                f"章扉の検出に失敗しました（p.{pages[0]}-{pages[-1]}）: {e}"
            ) from e

    seen: set[int] = set()
    merged = []
    for name, page in sorted(chapters, key=lambda c: c[1]):
        if page in seen:
            continue
        seen.add(page)
        merged.append((name, page))
    return merged


def refine_chapter_names(
    chapters: list[tuple[str, int]],
    output_dir: str,
    runner: Callable[[str, str], str],
    sheet_builder: Callable[[list[int], str], str],
    per_sheet: int = REFINE_PER_SHEET,
) -> list[tuple[str, int]]:
    """章扉ページだけを拡大したシートを作り、章名を書き写させて置き換える

    1パス目のサムネイルでは章番号バッジが小さく読めないため、番号を取り違える。
    ここで実際のページを大きく描画して読み直す。
    """
    pages = sorted(page for _, page in chapters)
    verified: dict[int, str] = {}

    for start in range(0, len(pages), per_sheet):
        chunk = pages[start:start + per_sheet]
        out_path = f"{output_dir}/titles_{chunk[0]}-{chunk[-1]}.png"
        image_path = sheet_builder(chunk, out_path)
        stdout = runner(build_title_prompt(chunk, image_path), image_path)
        verified.update(_parse_titles_json(stdout, chunk))

    # 拡大表示で章扉と確認できたページだけを残す（1パス目の誤検出を落とす）
    return [
        (verified[page] or original, page)
        for original, page in sorted(chapters, key=lambda c: c[1])
        if page in verified
    ]


def build_title_prompt(pages: list[int], image_path: str) -> str:
    """章名の書き写し用プロンプト（画像はベース名で参照する）"""
    page_list = "、".join(f"p.{p}" for p in pages)
    return (
        f"添付の画像 {Path(image_path).name} を Read ツールで開いてください。\n"
        f"この画像には PDF の {page_list} のページが、左上から右へ・次の行へと"
        "その順番で並んでいます。\n\n"
        "各ページについて2つ答えてください。\n"
        "1. そのページが本当に章の扉ページか（章番号や章タイトルが大きく置かれた"
        "ページ。本文・図表・目次のページは章扉ではありません）\n"
        "2. 章扉なら、**実際に印刷されている**章番号と章タイトルを書かれているとおりに"
        "書き写す（推測や補完はしない。読めない場合は空文字）\n\n"
        "以下の JSON のみを出力してください（説明文やコードフェンスは不要）:\n"
        '{"titles":[{"page":<ページ番号>,"is_chapter_start":true/false,'
        '"label":"<章番号と章タイトル>"}]}'
    )


def _parse_titles_json(stdout: str, pages: list[int]) -> dict[int, str]:
    """章名の書き写し結果を {ページ: 章名} にする（対象ページ以外は無視）"""
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(stdout[start:end + 1])
    except json.JSONDecodeError:
        return {}

    allowed = set(pages)
    labels = {}
    for item in data.get("titles", []):
        page = item.get("page")
        if page not in allowed:
            continue
        # 章扉と明示的に確認できたページだけを採用する
        # （欠落・null・文字列などは「確認できなかった」として捨てる）
        if item.get("is_chapter_start") is not True:
            continue
        labels[page] = str(item.get("label", "")).strip()
    return labels


def run_claude_cli(
    prompt: str,
    image_path: str,
    timeout: int = TIMEOUT_SECONDS,
    is_cancelled: Callable[[], bool] | None = None,
) -> str:
    """ローカルの claude CLI を非対話モードで呼び、応答テキストを返す

    画像の読み取りだけを許可し、書き込み系ツールは渡さない。
    ヘッドレスの claude は cwd 配下のファイルしか追加許可なしに Read できないため、
    画像のあるディレクトリを cwd にしてベース名で参照させる。

    is_cancelled が True を返したら、実行中のプロセスを終了して打ち切る
    （キャンセル後にGUIが最大 timeout 秒固まるのを防ぐ）。
    """
    workdir = str(Path(image_path).parent)
    try:
        process = subprocess.Popen(
            ["claude", "-p", "--allowedTools", "Read", "--output-format", "json", prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=workdir,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            "claude CLI が見つかりません。インストールとログインを確認してください。"
        ) from e

    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        try:
            stdout, stderr = process.communicate(
                timeout=max(0.05, min(_POLL_SECONDS, remaining))
            )
            break
        except subprocess.TimeoutExpired:
            if is_cancelled is not None and is_cancelled():
                _terminate(process)
                raise RuntimeError("キャンセルされました")
            if time.monotonic() >= deadline:
                _terminate(process)
                raise RuntimeError(
                    f"claude CLI が時間内に応答しませんでした（{timeout}秒）。"
                )

    if process.returncode != 0:
        raise RuntimeError(
            f"claude CLI がエラーを返しました (exit {process.returncode}):\n"
            f"{(stderr or stdout or '')[:300]}"
        )
    # --output-format json は {"result": "<assistantのテキスト>"} を返す
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout
    if isinstance(payload, dict) and "result" in payload:
        return str(payload["result"])
    return stdout


def _terminate(process) -> None:
    """実行中のプロセスを終了する（応答しなければ強制終了して回収する）"""
    process.terminate()
    try:
        process.communicate(timeout=_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        # kill しっぱなしにせず回収する（ゾンビを残さない）
        process.wait(timeout=_TERMINATE_GRACE_SECONDS)


def build_prompt(pages: list[int], image_path: str) -> str:
    """シート1枚分のプロンプトを組み立てる（画像はベース名で参照する）"""
    return (
        f"添付のコンタクトシート画像 {Path(image_path).name} を Read ツールで開いて分析してください。\n"
        f"これは PDF のページをサムネイル格子にしたもので、左上が PDF の {pages[0]} ページ目、"
        f"右方向・次の行へと順に並び、右下が {pages[-1]} ページ目です。\n\n"
        "書籍の「章扉ページ」（章番号や章タイトルが大きく置かれ、本文とは明らかに違う"
        "レイアウトのページ）だけを特定してください。本文・図表・目次のページは含めないでください。\n\n"
        "以下の JSON のみを出力してください（説明文やコードフェンスは不要）:\n"
        '{"chapters":[{"page":<PDFの物理ページ番号>,"label":"<章番号と章タイトル>"}]}\n'
        '章扉が無ければ {"chapters":[]} と出力してください。'
    )


def parse_chapters_json(stdout: str, page_count: int) -> list[tuple[str, int]]:
    """claude の出力から (章名, 物理ページ) のリストを取り出す"""
    # 前後に説明文やコードフェンスが付くことがあるので JSON 部分だけを取り出す
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"JSON が見つかりません: {stdout[:200]}")
    data = json.loads(stdout[start:end + 1])
    seen: set[int] = set()
    chapters: list[tuple[str, int]] = []
    for item in data["chapters"]:
        page = item["page"]
        if not isinstance(page, int) or not 1 <= page <= page_count:
            continue
        if page in seen:
            continue
        seen.add(page)
        chapters.append((str(item.get("label", "")).strip(), page))

    chapters.sort(key=lambda c: c[1])
    return chapters
