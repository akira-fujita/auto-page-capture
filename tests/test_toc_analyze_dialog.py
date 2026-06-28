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


def test_anchor_change_recomputes_ranges(qapp, image_paths):
    """FIX 2: アンカー変更で _recompute が呼ばれ result_ranges が変わる"""
    engine = _FakeEngine([TocEntry("第1章", 1), TocEntry("第2章", 45)])
    dialog = TocAnalyzeDialog(image_paths, engine=engine)
    # アンカー: 印刷p.1 = キャプチャ#8 → offset=7
    dialog.anchor_printed_spin.setValue(1)
    dialog.anchor_capture_spin.setValue(8)
    dialog._run_analyze()
    ranges_before = [ChapterRange(r.name, r.start, r.end) for r in dialog.result_ranges]

    # アンカーを変更: 印刷p.1 = キャプチャ#10 → offset=9
    dialog.anchor_capture_spin.setValue(10)
    ranges_after = dialog.result_ranges

    # offset が変わったので start が変わっているはず
    assert ranges_before != list(ranges_after), "アンカー変更後に ranges が更新されていない"
    assert ranges_after[0].start != ranges_before[0].start


class _RaisingEngine:
    """analyze() を呼ぶと RuntimeError を送出するフェイク"""
    def analyze(self, image_paths):
        raise RuntimeError("解析失敗")


def test_stale_state_reset_on_analyze_failure(qapp, image_paths, monkeypatch):
    """FIX 3: 解析失敗時に result_ranges がリセットされ apply_btn が無効になる"""
    # 1回目: 成功してステートを埋める
    engine = _FakeEngine([TocEntry("第1章", 1), TocEntry("第2章", 45)])
    dialog = TocAnalyzeDialog(image_paths, engine=engine)
    dialog.anchor_printed_spin.setValue(1)
    dialog.anchor_capture_spin.setValue(8)
    dialog._run_analyze()
    assert dialog.result_ranges  # 成功後は非空
    assert dialog.apply_btn.isEnabled()

    # 2回目: エンジンを失敗させる
    dialog.engine = _RaisingEngine()
    # QMessageBox.critical をモックして GUI ダイアログを抑制
    monkeypatch.setattr(
        "src.ui.toc_analyze_dialog.QMessageBox.critical", lambda *a, **kw: None
    )
    dialog._run_analyze()

    assert dialog.result_ranges == []
    assert dialog.apply_btn.isEnabled() is False
