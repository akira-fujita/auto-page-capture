# tests/test_pdf_toc_analyze_dialog.py
import sys
import tempfile
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from src.export.toc_analyzer import TocEntry, ChapterRange
from src.ui.pdf_toc_analyze_dialog import PdfTocAnalyzeDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class _FakeEngine:
    def __init__(self, entries):
        self._entries = entries
        self.called_with = None

    def analyze(self, image_paths):
        self.called_with = list(image_paths)
        return self._entries


class _FakeSplitter:
    def __init__(self):
        self.rendered = []

    def render_page_image(self, pdf_path, page_index, output_path, max_height=2000):
        self.rendered.append(page_index)
        Path(output_path).write_bytes(b"PNG")  # ダミー
        return Path(output_path)


def _dialog(entries, page_count=188):
    engine = _FakeEngine(entries)
    splitter = _FakeSplitter()
    d = PdfTocAnalyzeDialog(Path("/tmp/book.pdf"), page_count, engine=engine, splitter=splitter)
    return d, engine, splitter


def test_inclusive_range_renders_correct_pages(qapp):
    d, engine, splitter = _dialog([TocEntry("第1章", 1)])
    d.toc_start_spin.setValue(3)
    d.toc_end_spin.setValue(5)  # inclusive: PDFページ 3,4,5 → index 2,3,4
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(11)
    d._run_analyze()
    assert splitter.rendered == [2, 3, 4]
    # engine には3枚の画像が渡る
    assert len(engine.called_with) == 3


def test_anchor_offset_maps_to_zero_based_start(qapp):
    d, engine, splitter = _dialog([TocEntry("第1章", 1), TocEntry("第2章", 45)])
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(11)  # offset = 11 - 1 = 10
    d._run_analyze()
    # 第1章: start = 1 + 10 - 1 = 10, 第2章: start = 45 + 10 - 1 = 54
    assert [ (c.name, c.start) for c in d.result_ranges ] == [("第1章", 10), ("第2章", 54)]


def test_out_of_range_entry_is_warned(qapp):
    d, engine, splitter = _dialog([TocEntry("第1章", 1), TocEntry("付録", 900)], page_count=188)
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(11)
    d._run_analyze()
    assert [c.name for c in d.result_ranges] == ["第1章"]
    assert len(d.warnings) == 1


def test_preface_option_prepends_front_matter(qapp):
    d, engine, splitter = _dialog([TocEntry("第1章", 1)], page_count=188)
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(11)  # 第1章 start = 10 → 前付け 0..9 が存在
    d.preface_check.setChecked(True)
    d._run_analyze()
    assert d.result_ranges[0].name == "前付け"
    assert d.result_ranges[0].start == 0
    assert d.result_ranges[0].end == 9
    assert d.result_ranges[1].name == "第1章"


def test_analyze_failure_resets_state(qapp, monkeypatch):
    class _Boom:
        def analyze(self, paths):
            raise RuntimeError("boom")
    splitter = _FakeSplitter()
    d = PdfTocAnalyzeDialog(Path("/tmp/b.pdf"), 188, engine=_Boom(), splitter=splitter)
    monkeypatch.setattr(
        "src.ui.pdf_toc_analyze_dialog.QMessageBox.critical", lambda *a, **k: None
    )
    d._run_analyze()
    assert d.result_ranges == []
    assert d.apply_btn.isEnabled() is False


def test_analyze_file_not_found_resets_state(qapp, monkeypatch):
    class _Missing:
        def analyze(self, paths):
            raise FileNotFoundError("claude not found")
    splitter = _FakeSplitter()
    d = PdfTocAnalyzeDialog(Path("/tmp/b.pdf"), 188, engine=_Missing(), splitter=splitter)
    monkeypatch.setattr(
        "src.ui.pdf_toc_analyze_dialog.QMessageBox.critical", lambda *a, **k: None
    )
    d._run_analyze()
    assert d.result_ranges == []
    assert d.apply_btn.isEnabled() is False


def _mixed_entries():
    """章・部・巻末が混在するエントリ（前付けは既に別処理で除外済み想定）"""
    return [
        TocEntry("1章 シンプリシティ", 1),
        TocEntry("第I部 やること", 5),
        TocEntry("2章 今すぐ減量を", 7),
        TocEntry("参考文献", 159),
        TocEntry("索引", 165),
    ]


def test_after_analyze_all_rows_checked(qapp):
    d, engine, splitter = _dialog(_mixed_entries())
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(17)
    d._run_analyze()
    # 解析直後は全行チェック済み → selected == result
    assert [c.name for c in d.selected_ranges] == [c.name for c in d.result_ranges]
    assert d.apply_btn.isEnabled() is True


def test_chapter_only_button_keeps_only_chapters(qapp):
    d, engine, splitter = _dialog(_mixed_entries())
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(17)
    d._run_analyze()
    d._on_chapter_only()
    assert [c.name for c in d.selected_ranges] == ["1章 シンプリシティ", "2章 今すぐ減量を"]


def test_select_none_disables_apply(qapp):
    d, engine, splitter = _dialog(_mixed_entries())
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(17)
    d._run_analyze()
    d._set_all_checked(False)
    assert d.selected_ranges == []
    assert d.apply_btn.isEnabled() is False


def test_chapter_only_no_match_warns_and_keeps_state(qapp, monkeypatch):
    d, engine, splitter = _dialog([TocEntry("参考文献", 159), TocEntry("索引", 165)])
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(17)
    d._run_analyze()
    calls = []
    monkeypatch.setattr(
        "src.ui.pdf_toc_analyze_dialog.QMessageBox.information",
        lambda *a, **k: calls.append(a),
    )
    before = [c.name for c in d.selected_ranges]
    d._on_chapter_only()
    assert len(calls) == 1  # 警告が出た
    assert [c.name for c in d.selected_ranges] == before  # 状態は不変


def test_manual_uncheck_updates_selected_and_apply(qapp):
    from PyQt6.QtCore import Qt
    d, engine, splitter = _dialog(_mixed_entries())
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(17)
    d._run_analyze()
    # 先頭行(1章)のチェックを外す
    d.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert "1章 シンプリシティ" not in [c.name for c in d.selected_ranges]
    assert d.apply_btn.isEnabled() is True


def test_selection_survives_anchor_change(qapp):
    """章のみ/手動選択がアンカー変更(recompute)で失われないこと"""
    d, engine, splitter = _dialog(_mixed_entries())
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(17)
    d._run_analyze()
    d._on_chapter_only()
    before = [c.name for c in d.selected_ranges]
    assert before == ["1章 シンプリシティ", "2章 今すぐ減量を"]
    # アンカー変更で recompute が走っても選択は維持される
    d.anchor_pdf_spin.setValue(18)
    assert [c.name for c in d.selected_ranges] == before


def test_selection_preserved_for_duplicate_names(qapp):
    """同名の行が複数あっても、どの行を外したかが recompute で保持される"""
    from PyQt6.QtCore import Qt
    entries = [TocEntry("同名", 10), TocEntry("同名", 20), TocEntry("2章", 30)]
    d, engine, splitter = _dialog(entries)
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(1)  # offset 0
    d._run_analyze()
    # 先頭の「同名」だけ外す
    d.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    # アンカー変更で recompute（非リセット）
    d.anchor_pdf_spin.setValue(2)
    assert d.table.item(0, 0).checkState() == Qt.CheckState.Unchecked  # 外した行は維持
    assert d.table.item(1, 0).checkState() == Qt.CheckState.Checked    # もう一方は維持


def test_preface_check_toggle_triggers_recompute(qapp):
    """FIX 1: preface_check の toggled シグナルが _recompute を呼ぶこと"""
    # offset=10: 第1章 start = 1 + 10 - 1 = 10 > 0 → 前付けが生まれる
    d, engine, splitter = _dialog([TocEntry("第1章", 1)], page_count=188)
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(11)  # offset = 11 - 1 = 10
    d._run_analyze()
    # 前付けなしの状態を確認
    assert d.result_ranges[0].name != "前付け"

    # True に切り替え → 自動で recompute → 前付けが先頭に来る
    d.preface_check.setChecked(True)
    assert d.result_ranges[0].name == "前付け"

    # False に戻す → 前付けが消える
    d.preface_check.setChecked(False)
    assert d.result_ranges[0].name != "前付け"
