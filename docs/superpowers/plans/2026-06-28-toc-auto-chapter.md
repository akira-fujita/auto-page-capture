# 目次自動解析による章分割 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** キャプチャ済みの目次画像を `claude` CLI に解析させ、章名と印刷ページ番号から章境界を自動算出して `ChapterDialog` に流し込む。

**Architecture:** 3層構成。純粋ロジック(offset計算・章変換)を `src/export/toc_analyzer.py` に、`claude` CLI 呼び出しを同ファイルの注入可能エンジンに、UIを薄い `src/ui/toc_analyze_dialog.py` に置く。`ChapterDialog` はボタン追加と結果反映だけ。

**Tech Stack:** Python 3.10+, PyQt6, `subprocess`(`claude` CLI 呼び出し), pytest。

## Global Constraints

- Python 3.10+ 構文(`list[...]`, `X | None` 等)を使用。
- 追加の pip 依存は入れない(標準ライブラリ `subprocess` / `json` のみ)。
- UI 文言は日本語。
- 層の依存方向は `ui → export` のみ。`export/` から `ui/` を import しない(`Chapter` を export 層で使わず、同形の `ChapterRange` を定義する)。
- `Chapter` dataclass の規約: `name: str`, `start: int`(0始まり), `end: int`(0始まり・包含)。
- TDD: 各タスクはテスト先行。コミットはタスク単位。

---

### Task 1: 純粋ロジック (TocEntry / ChapterRange / compute_offset / entries_to_chapters)

**Files:**
- Create: `src/export/toc_analyzer.py`
- Test: `tests/test_toc_analyzer.py`

**Interfaces:**
- Produces:
  - `TocEntry(name: str, printed_page: int)` dataclass
  - `ChapterRange(name: str, start: int, end: int)` dataclass(`start`/`end` は0始まり包含)
  - `compute_offset(anchor_capture_no: int, anchor_printed_page: int) -> int`
  - `entries_to_chapters(entries: list[TocEntry], offset: int, total_pages: int) -> tuple[list[ChapterRange], list[str]]`(章リストと警告メッセージ列を返す)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_toc_analyzer.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_toc_analyzer.py -v`
Expected: FAIL(ImportError: cannot import name ... / module not found)

- [ ] **Step 3: Write minimal implementation**

```python
# src/export/toc_analyzer.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_toc_analyzer.py -v`
Expected: PASS(5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/export/toc_analyzer.py tests/test_toc_analyzer.py
git commit -m "feat: add TOC offset/chapter-range logic"
```

---

### Task 2: ClaudeTocEngine(claude CLI 呼び出しと JSON 抽出)

**Files:**
- Modify: `src/export/toc_analyzer.py`(末尾に追加)
- Test: `tests/test_toc_analyzer.py`(追記)

**Interfaces:**
- Consumes: `TocEntry`(Task 1)
- Produces:
  - `_extract_entries(stdout: str) -> list[TocEntry]`(JSON 抽出。テスト用に分離)
  - `ClaudeTocEngine.analyze(image_paths: list[Path]) -> list[TocEntry]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_toc_analyzer.py に追記
import json
from pathlib import Path

from src.export.toc_analyzer import _extract_entries, ClaudeTocEngine


def test_extract_entries_plain_json():
    out = '[{"name": "第1章", "page": 1}, {"name": "第2章", "page": 45}]'
    entries = _extract_entries(out)
    assert entries == [TocEntry("第1章", 1), TocEntry("第2章", 45)]


def test_extract_entries_with_codeblock_and_prose():
    out = "解析しました:\n```json\n[{\"name\": \"序章\", \"page\": 3}]\n```\nどうぞ"
    entries = _extract_entries(out)
    assert entries == [TocEntry("序章", 3)]


def test_extract_entries_raises_on_garbage():
    import pytest
    with pytest.raises(ValueError):
        _extract_entries("ページ番号が読めませんでした")


def test_claude_engine_invokes_cli_and_parses(monkeypatch):
    captured = {}

    class _Result:
        stdout = json.dumps({"result": '[{"name": "第1章", "page": 1}]'})

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_toc_analyzer.py -v -k "extract or claude_engine"`
Expected: FAIL(ImportError: `_extract_entries` / `ClaudeTocEngine`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/export/toc_analyzer.py の冒頭 import に追加
import json
import subprocess
from pathlib import Path

# ファイル末尾に追加

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
        # --output-format json は {"result": "<assistantのテキスト>"} を返す
        try:
            payload = json.loads(result.stdout)
            inner = payload.get("result", result.stdout)
        except json.JSONDecodeError:
            inner = result.stdout
        return _extract_entries(inner)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_toc_analyzer.py -v`
Expected: PASS(全テスト)

- [ ] **Step 5: Commit**

```bash
git add src/export/toc_analyzer.py tests/test_toc_analyzer.py
git commit -m "feat: add ClaudeTocEngine with JSON extraction"
```

---

### Task 3: TocAnalyzeDialog(目次解析UI・エンジン注入可)

**Files:**
- Create: `src/ui/toc_analyze_dialog.py`
- Test: `tests/test_toc_analyze_dialog.py`

**Interfaces:**
- Consumes: `ClaudeTocEngine`, `entries_to_chapters`, `compute_offset`, `ChapterRange`(Task 1-2)
- Produces:
  - `TocAnalyzeDialog(image_paths: list[Path], engine=None, parent=None)`
  - `dialog.result_ranges: list[ChapterRange]`(確定後に参照)
  - 内部メソッド `_run_analyze()`(解析実行→`self._entries` 格納)、`_recompute()`(anchor 反映→`result_ranges`/警告更新)

> **プレビューは確認専用(読み取り専用)**。章名や境界の微調整は確定後に `ChapterDialog` 側で行う(既に rename / 境界クリックを実装済みのため二重実装を避ける)。spec の「編集可」表記はこの方針に置き換える。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_toc_analyze_dialog.py
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image
from PyQt6.QtWidgets import QApplication

from src.export.toc_analyzer import TocEntry, ChapterRange
from src.ui.toc_analyze_dialog import TocAnalyzeDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def image_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = []
        for i in range(60):
            p = Path(tmpdir) / f"page_{i}.png"
            Image.new("RGB", (20, 20), "white").save(p, "PNG")
            paths.append(p)
        yield paths


class _FakeEngine:
    def __init__(self, entries):
        self._entries = entries
        self.called_with = None

    def analyze(self, image_paths):
        self.called_with = list(image_paths)
        return self._entries


def test_analyze_then_recompute_produces_ranges(qapp, image_paths):
    engine = _FakeEngine([TocEntry("第1章", 1), TocEntry("第2章", 45)])
    dialog = TocAnalyzeDialog(image_paths, engine=engine)

    # 目次ページ範囲: キャプチャ#5〜#6
    dialog.toc_start_spin.setValue(5)
    dialog.toc_end_spin.setValue(6)
    # アンカー: 印刷p.1 = キャプチャ#8
    dialog.anchor_printed_spin.setValue(1)
    dialog.anchor_capture_spin.setValue(8)

    dialog._run_analyze()

    # エンジンには #5,#6 の画像だけ渡る(0始まりで index 4,5)
    assert engine.called_with == [image_paths[4], image_paths[5]]
    assert dialog.result_ranges == [
        ChapterRange("第1章", 7, 50),
        ChapterRange("第2章", 51, 59),
    ]


def test_out_of_range_entry_is_warned(qapp, image_paths):
    engine = _FakeEngine([TocEntry("第1章", 1), TocEntry("付録", 320)])
    dialog = TocAnalyzeDialog(image_paths, engine=engine)
    dialog.anchor_printed_spin.setValue(1)
    dialog.anchor_capture_spin.setValue(8)
    dialog._run_analyze()
    assert [c.name for c in dialog.result_ranges] == ["第1章"]
    assert len(dialog.warnings) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_toc_analyze_dialog.py -v`
Expected: FAIL(ModuleNotFoundError: `src.ui.toc_analyze_dialog`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/ui/toc_analyze_dialog.py
"""目次画像を解析して章範囲を提案するダイアログ"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
    QPushButton, QGroupBox, QTableWidget, QTableWidgetItem,
    QMessageBox, QApplication,
)
from PyQt6.QtCore import Qt

from src.export.toc_analyzer import (
    ClaudeTocEngine, compute_offset, entries_to_chapters,
)


class TocAnalyzeDialog(QDialog):
    """目次から章を自動解析するダイアログ"""

    def __init__(self, image_paths: list[Path], engine=None, parent=None):
        super().__init__(parent)
        self.image_paths = image_paths
        self.engine = engine or ClaudeTocEngine()
        self._entries = []
        self.result_ranges = []
        self.warnings = []

        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("目次から章を自動解析")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        n = len(self.image_paths)

        # ① 目次ページ範囲
        toc_group = QGroupBox("① 目次のページ範囲")
        toc_layout = QHBoxLayout(toc_group)
        self.toc_start_spin = QSpinBox()
        self.toc_start_spin.setRange(1, max(1, n))
        self.toc_start_spin.setPrefix("キャプチャ #")
        self.toc_end_spin = QSpinBox()
        self.toc_end_spin.setRange(1, max(1, n))
        self.toc_end_spin.setValue(min(2, n))
        self.toc_end_spin.setPrefix("キャプチャ #")
        toc_layout.addWidget(self.toc_start_spin)
        toc_layout.addWidget(QLabel("〜"))
        toc_layout.addWidget(self.toc_end_spin)
        toc_layout.addStretch()
        layout.addWidget(toc_group)

        # ② アンカー
        anchor_group = QGroupBox("② ページ番号アンカー(ズレ補正)")
        anchor_layout = QHBoxLayout(anchor_group)
        self.anchor_printed_spin = QSpinBox()
        self.anchor_printed_spin.setRange(1, 99999)
        self.anchor_printed_spin.setPrefix("印刷 p.")
        self.anchor_capture_spin = QSpinBox()
        self.anchor_capture_spin.setRange(1, max(1, n))
        self.anchor_capture_spin.setPrefix("キャプチャ #")
        anchor_layout.addWidget(self.anchor_printed_spin)
        anchor_layout.addWidget(QLabel("="))
        anchor_layout.addWidget(self.anchor_capture_spin)
        anchor_layout.addStretch()
        layout.addWidget(anchor_group)

        # 解析ボタン
        self.analyze_btn = QPushButton("解析する")
        self.analyze_btn.clicked.connect(self._run_analyze)
        layout.addWidget(self.analyze_btn)

        # ③ プレビュー
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["章名", "印刷p", "→ キャプチャ範囲"])
        layout.addWidget(self.table)

        self.warning_label = QLabel()
        self.warning_label.setStyleSheet("color: #d32f2f;")
        self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)

        # ボタン
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        self.apply_btn = QPushButton("この内容で章を設定")
        self.apply_btn.clicked.connect(self.accept)
        self.apply_btn.setEnabled(False)
        btn_layout.addWidget(self.apply_btn)
        layout.addLayout(btn_layout)

    def _selected_toc_images(self) -> list[Path]:
        start = self.toc_start_spin.value() - 1
        end = self.toc_end_spin.value()  # exclusive 用に+0(slice は end まで)
        if end < self.toc_start_spin.value():
            end = self.toc_start_spin.value()
        return self.image_paths[start:end]

    def _run_analyze(self):
        images = self._selected_toc_images()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._entries = self.engine.analyze(images)
        except FileNotFoundError:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(
                self, "エラー",
                "claude CLI が見つかりませんでした。手動でページを入力してください。",
            )
            return
        except Exception as e:  # タイムアウト・JSON不可など
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(
                self, "エラー",
                f"目次の解析に失敗しました:\n{e}\n\n手動でページを入力してください。",
            )
            return
        QApplication.restoreOverrideCursor()
        self._recompute()

    def _recompute(self):
        offset = compute_offset(
            self.anchor_capture_spin.value(), self.anchor_printed_spin.value()
        )
        self.result_ranges, self.warnings = entries_to_chapters(
            self._entries, offset, len(self.image_paths)
        )
        self._refresh_table()
        self.apply_btn.setEnabled(bool(self.result_ranges))

    def _refresh_table(self):
        self.table.setRowCount(len(self.result_ranges))
        for i, c in enumerate(self.result_ranges):
            self.table.setItem(i, 0, QTableWidgetItem(c.name))
            self.table.setItem(i, 2, QTableWidgetItem(f"p.{c.start + 1}-{c.end + 1}"))
        self.warning_label.setText("\n".join(self.warnings))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_toc_analyze_dialog.py -v`
Expected: PASS(2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ui/toc_analyze_dialog.py tests/test_toc_analyze_dialog.py
git commit -m "feat: add TocAnalyzeDialog with injectable engine"
```

---

### Task 4: ChapterDialog への組み込み(ボタン追加＋結果反映)

**Files:**
- Modify: `src/ui/chapter_dialog.py`
- Test: `tests/test_chapter_dialog.py`(追記)

**Interfaces:**
- Consumes: `TocAnalyzeDialog`(Task 3), `ChapterRange`
- Produces: `ChapterDialog._apply_toc_ranges(ranges: list[ChapterRange]) -> None`(章リストを置換し再描画。UIから独立してテスト可)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chapter_dialog.py に追記
from src.export.toc_analyzer import ChapterRange


def test_apply_toc_ranges_replaces_chapters(qapp, image_paths):
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as outdir:
        dialog = ChapterDialog(image_paths, Path(outdir), keep_images=True)
        ranges = [
            ChapterRange("はじめに", 0, 0),
            ChapterRange("本編", 1, 1),
        ]
        dialog._apply_toc_ranges(ranges)
        assert [c.name for c in dialog.chapters] == ["はじめに", "本編"]
        assert dialog.chapters[0].start == 0 and dialog.chapters[0].end == 0
        assert dialog.chapters[1].start == 1 and dialog.chapters[1].end == 1
        # 章リスト表示も更新される
        assert dialog.chapter_list.count() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chapter_dialog.py::test_apply_toc_ranges_replaces_chapters -v`
Expected: FAIL(AttributeError: `_apply_toc_ranges`)

- [ ] **Step 3: Write minimal implementation**

`src/ui/chapter_dialog.py` の import に追加:

```python
from src.export.toc_analyzer import ChapterRange
```

`_init_ui` の説明文(`instruction`)直後にボタンを追加:

```python
        toc_btn = QPushButton("目次から章を自動解析")
        toc_btn.clicked.connect(self._open_toc_analyze)
        layout.addWidget(toc_btn)
```

クラスにメソッドを追加(`_export_pdfs` の前あたり):

```python
    def _open_toc_analyze(self):
        """目次解析ダイアログを開き、確定したら章を反映"""
        from src.ui.toc_analyze_dialog import TocAnalyzeDialog
        dialog = TocAnalyzeDialog(self.image_paths, parent=self)
        if dialog.exec() and dialog.result_ranges:
            self._apply_toc_ranges(dialog.result_ranges)

    def _apply_toc_ranges(self, ranges: "list[ChapterRange]"):
        """解析結果で章リストを置換して再描画する"""
        self.chapters = [
            Chapter(name=r.name, start=r.start, end=r.end) for r in ranges
        ]
        self._recalculate_chapter_ranges()
        self._update_chapter_list()
        self._update_thumbnails()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chapter_dialog.py -v`
Expected: PASS(既存 + 新規)

- [ ] **Step 5: Commit**

```bash
git add src/ui/chapter_dialog.py tests/test_chapter_dialog.py
git commit -m "feat: wire TOC auto-analyze into ChapterDialog"
```

---

### Task 5: ドキュメント更新と全テスト・手動確認

**Files:**
- Modify: `README.md`(機能一覧)

- [ ] **Step 1: README の機能一覧に追記**

`## 機能 / Features` の章分割の項目付近に追加:

```markdown
- **目次から章を自動解析** / **Auto chapter detection from TOC** — キャプチャした目次ページを `claude` CLI に解析させ、章名とページ番号から章境界を自動算出（印刷ページとキャプチャ枚数のズレはアンカー1点で補正） / Parse a captured table-of-contents via the `claude` CLI to auto-detect chapter boundaries (a one-point page anchor bridges printed vs captured page numbers)
```

依存表(`### 依存ライブラリ`)の下に注記を追加:

```markdown
> **目次自動解析** は `claude` CLI（Claude Code）がインストール済みで、ネットワーク接続があることを前提とします。従量 API 課金は発生せず、サブスクリプション枠で動作します。
```

- [ ] **Step 2: 全テストを実行**

Run: `pytest -v`
Expected: 全 PASS(macOS Vision 不在環境では `test_ocr_engine` は skip 可)

- [ ] **Step 3: 手動確認(ネットワーク依存のため自動テスト外)**

1. `python main.py` で起動し、数ページキャプチャ(または既存画像で章分割ダイアログを開く)。
2. 「目次から章を自動解析」→ 目次ページ範囲とアンカーを指定 →「解析する」。
3. `claude` CLI が画像を読めて JSON を返すこと、プレビューに章が並ぶことを確認。
   - もし `claude -p` が画像パスを Read できない場合は、画像を base64 で渡す方式へ切替(spec の代替案)。
4. 「この内容で章を設定」で `ChapterDialog` の章リストが置き換わることを確認。

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document TOC auto-chapter feature"
```

---

## Codex レビュー

全タスク完了後、`claude/toc-auto-chapter` の差分に対して Codex レビューをかける(`/code-review` または codex rescue 経由)。指摘は receiving-code-review の方針で検証してから取り込む。
