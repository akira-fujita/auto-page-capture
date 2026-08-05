# tests/test_pdf_toc_analyze_dialog.py
import sys
import tempfile
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

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


def test_toc_dialog_key_widgets_have_tooltips(qapp):
    d, engine, splitter = _dialog([TocEntry("第1章", 1)])
    assert d.anchor_printed_spin.toolTip()
    assert d.anchor_pdf_spin.toolTip()
    assert d.chapter_only_btn.toolTip()
    assert d.analyze_btn.toolTip()


def test_toc_dialog_help_button_shows_usage(qapp, monkeypatch):
    d, engine, splitter = _dialog([TocEntry("第1章", 1)])
    shown = []
    monkeypatch.setattr(
        "src.ui.pdf_toc_analyze_dialog.QMessageBox.information",
        lambda *a, **k: shown.append(a),
    )
    d.help_btn.click()
    assert shown, "使い方ダイアログが表示されていない"
    body = shown[0][2]  # information(parent, title, text)
    assert "解析" in body and "章のみ" in body


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


def test_cover_detect_button_exists(qapp):
    """目次にページ番号が無い本向けに、章扉検出のボタンがある"""
    d, _, _ = _dialog([])
    assert hasattr(d, "cover_btn"), "章扉検出ボタンが無い"
    assert d.cover_btn.toolTip(), "使い方が分かるツールチップが要る"


def test_cover_detect_fills_ranges(qapp, monkeypatch):
    """章扉検出の結果をそのまま章範囲にする（アンカー不要・物理ページ直取り）"""
    d, _, _ = _dialog([], page_count=211)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        d, "_detect_covers_with_progress",
        lambda: [("序章", 15), ("第1章", 35), ("第2章", 79)],
    )
    d._run_cover_detect()

    assert [(c.name, c.start, c.end) for c in d.result_ranges] == [
        ("序章", 14, 33),
        ("第1章", 34, 77),
        ("第2章", 78, 210),
    ]
    assert d.apply_btn.isEnabled()
    assert d.table.rowCount() == 3


def test_cover_result_survives_anchor_change(qapp, monkeypatch):
    """章扉検出は物理ページ直取りなので、アンカーを動かしても結果を壊さない"""
    d, _, _ = _dialog([], page_count=211)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        d, "_detect_covers_with_progress", lambda: [("序章", 15), ("第1章", 35)]
    )
    d._run_cover_detect()
    before = [(c.name, c.start, c.end) for c in d.result_ranges]

    d.anchor_printed_spin.setValue(5)
    d.anchor_pdf_spin.setValue(40)

    assert [(c.name, c.start, c.end) for c in d.result_ranges] == before


def test_summary_text_reflects_detection_source(qapp, monkeypatch):
    """サマリ文言は検出元（目次 / 章扉）に合わせる"""
    d, _, _ = _dialog([], page_count=211)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        d, "_detect_covers_with_progress", lambda: [("序章", 15), ("第1章", 35)]
    )
    d._run_cover_detect()
    assert "章扉" in d.summary_label.text()
    assert "2 件" in d.summary_label.text()


def test_cover_detect_confirms_and_runs_in_worker(qapp, monkeypatch):
    """実行前に確認を取り、検出はワーカースレッドで進捗つきで走る"""
    from PyQt6.QtWidgets import QMessageBox, QProgressDialog
    import src.ui.pdf_toc_analyze_dialog as mod

    events = []

    class _FakeSignal:
        def __init__(self):
            self._slots = []

        def connect(self, slot):
            self._slots.append(slot)

        def emit(self, *args):
            for slot in self._slots:
                slot(*args)

    class FakeWorker:
        def __init__(self, detect_fn, parent=None):
            events.append("worker")
            self.progress = _FakeSignal()
            self.finished_ok = _FakeSignal()
            self.failed = _FakeSignal()
            self.cancelled = _FakeSignal()

        def start(self):
            self.finished_ok.emit([("序章", 15), ("第1章", 35)])

        def cancel(self):
            pass

        def is_cancelled(self):
            return False

        def isRunning(self):
            return False

        def wait(self):
            pass

    monkeypatch.setattr(mod, "_CoverDetectWorker", FakeWorker)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **kw: events.append(("question", a[2])) or QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QProgressDialog, "exec", lambda self: events.append("progress"))
    monkeypatch.setattr(QProgressDialog, "close", lambda self: None)

    d, _, _ = _dialog([], page_count=211)
    d._run_cover_detect()

    kinds = [e[0] if isinstance(e, tuple) else e for e in events]
    assert kinds == ["question", "worker", "progress"], kinds
    # 確認文にコスト（利用枠）の明示があること
    question_text = [e[1] for e in events if isinstance(e, tuple)][0]
    assert "利用枠" in question_text
    assert len(d.result_ranges) == 2


def test_cover_detect_declined_does_nothing(qapp, monkeypatch):
    """確認で「いいえ」なら検出せず、既存の状態を変えない"""
    from PyQt6.QtWidgets import QMessageBox

    called = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.No
    )
    d, _, _ = _dialog([], page_count=211)
    monkeypatch.setattr(
        d, "_detect_chapter_covers", lambda: called.append("detect") or []
    )
    d._run_cover_detect()
    assert called == []
    assert d.result_ranges == []


def test_text_detect_button_fills_ranges_without_claude(qapp, monkeypatch):
    """claude を使わないテキスト検出でも章範囲を埋められる"""
    from src.export.pdf_splitter import DetectionResult

    d, _, _ = _dialog([], page_count=100)
    assert hasattr(d, "text_btn"), "テキスト検出ボタンが無い"
    monkeypatch.setattr(
        d.splitter, "detect_chapters_auto",
        lambda path: DetectionResult([("第1章", 10), ("第2章", 40)], "heading", True),
        raising=False,
    )
    d._run_text_detect()

    assert [(c.name, c.start, c.end) for c in d.result_ranges] == [
        ("第1章", 9, 38),
        ("第2章", 39, 99),
    ]
    assert "本文見出し" in d.summary_label.text()


def test_text_detect_printed_toc_pages_go_through_anchor(qapp, monkeypatch):
    """目次の印字ページはアンカー補正を通す（物理ページ扱いにしない）"""
    from src.export.pdf_splitter import DetectionResult

    d, _, _ = _dialog([], page_count=100)
    d.anchor_printed_spin.setValue(1)
    d.anchor_pdf_spin.setValue(11)  # 印刷 p.1 = PDF 11ページ目（offset +10）
    monkeypatch.setattr(
        d.splitter, "detect_chapters_auto",
        lambda path: DetectionResult([("第1章", 1), ("第2章", 30)], "toc", True),
        raising=False,
    )
    d._run_text_detect()

    # 印刷 p.1 → PDF 11ページ目 = index 10
    assert [(c.name, c.start) for c in d.result_ranges] == [("第1章", 10), ("第2章", 39)]


def test_cover_detect_cancel_is_not_reported_as_not_found(qapp, monkeypatch):
    """キャンセル時は「章扉が見つかりません」と誤報しない"""
    from PyQt6.QtWidgets import QMessageBox, QProgressDialog
    import src.ui.pdf_toc_analyze_dialog as mod

    messages = []

    class _FakeSignal:
        def __init__(self):
            self._slots = []

        def connect(self, slot):
            self._slots.append(slot)

        def emit(self, *args):
            for slot in self._slots:
                slot(*args)

    class CancelledWorker:
        def __init__(self, detect_fn, parent=None):
            self.progress = _FakeSignal()
            self.finished_ok = _FakeSignal()
            self.failed = _FakeSignal()
            self.cancelled = _FakeSignal()

        def start(self):
            self.cancelled.emit()

        def cancel(self):
            pass

        def is_cancelled(self):
            return True

        def isRunning(self):
            return False

        def wait(self):
            pass

    monkeypatch.setattr(mod, "_CoverDetectWorker", CancelledWorker)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: messages.append(a[1:3]))
    monkeypatch.setattr(QProgressDialog, "exec", lambda self: None)
    monkeypatch.setattr(QProgressDialog, "close", lambda self: None)

    d, _, _ = _dialog([], page_count=211)
    d._run_cover_detect()

    assert messages == [], f"キャンセル時に余計なメッセージを出さない: {messages}"


def test_preface_toggle_rebuilds_after_page_detection(qapp, monkeypatch):
    """章扉/テキスト検出のあとでも「前付け」チェックが効く"""
    d, _, _ = _dialog([], page_count=100)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        d, "_detect_covers_with_progress", lambda: [("第1章", 10), ("第2章", 40)]
    )
    d._run_cover_detect()
    assert [c.name for c in d.result_ranges] == ["第1章", "第2章"]

    d.preface_check.setChecked(True)
    assert [c.name for c in d.result_ranges] == ["前付け", "第1章", "第2章"]
    assert d.result_ranges[0].start == 0 and d.result_ranges[0].end == 8

    d.preface_check.setChecked(False)
    assert [c.name for c in d.result_ranges] == ["第1章", "第2章"]


def test_reset_state_clears_detection_mode(qapp, monkeypatch):
    """目次解析の失敗で状態を戻したら、前の検出元の表示は残さない"""
    d, _, _ = _dialog([], page_count=100)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        d, "_detect_covers_with_progress", lambda: [("第1章", 10), ("第2章", 40)]
    )
    d._run_cover_detect()
    assert "章扉" in d.summary_label.text()

    d._reset_state()
    assert "章扉" not in d.summary_label.text()


def test_detected_count_excludes_preface_row(qapp, monkeypatch):
    """前付け行は検出件数に数えない"""
    d, _, _ = _dialog([], page_count=100)
    d.preface_check.setChecked(True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        d, "_detect_covers_with_progress", lambda: [("第1章", 10), ("第2章", 40)]
    )
    d._run_cover_detect()
    assert len(d.result_ranges) == 3  # 前付け + 2章
    assert "2 件検出" in d.summary_label.text(), d.summary_label.text()


def test_worker_runs_off_gui_thread_and_cancels(qapp):
    """実 QThread で: GUIスレッド外で動き、キャンセルが伝わる"""
    import threading
    import time
    from PyQt6.QtCore import QEventLoop, QTimer
    from src.ui.pdf_toc_analyze_dialog import _CoverDetectWorker, _CoverDetectCancelled

    gui_thread = threading.current_thread().ident
    observed = {}
    started = threading.Event()

    def slow_detect():
        observed["thread"] = threading.current_thread().ident
        started.set()
        # キャンセル要求が来るまで待ち、来たら打ち切る
        for _ in range(200):
            if worker.is_cancelled():
                raise _CoverDetectCancelled()
            time.sleep(0.01)
        return [("第1章", 10)]

    worker = _CoverDetectWorker(slow_detect)
    loop = QEventLoop()
    outcome = {}
    worker.cancelled.connect(lambda: (outcome.update(cancelled=True), loop.quit()))
    worker.finished_ok.connect(lambda c: (outcome.update(covers=c), loop.quit()))
    worker.failed.connect(lambda m: (outcome.update(error=m), loop.quit()))

    worker.start()
    assert started.wait(5), "ワーカーが動き出さない"
    QTimer.singleShot(0, worker.cancel)
    QTimer.singleShot(5000, loop.quit)  # 保険
    loop.exec()
    worker.wait()

    assert observed["thread"] != gui_thread, "GUIスレッドで実行されている"
    assert outcome.get("cancelled") is True, outcome


def test_cover_detect_failure_shows_single_message(qapp, monkeypatch):
    """失敗時にエラーと「見つかりません」を二重に出さない"""
    from PyQt6.QtWidgets import QProgressDialog
    import src.ui.pdf_toc_analyze_dialog as mod

    shown = []

    class _FakeSignal:
        def __init__(self):
            self._slots = []

        def connect(self, slot):
            self._slots.append(slot)

        def emit(self, *args):
            for slot in self._slots:
                slot(*args)

    class FailingWorker:
        def __init__(self, detect_fn, parent=None):
            self.progress = _FakeSignal()
            self.finished_ok = _FakeSignal()
            self.failed = _FakeSignal()
            self.cancelled = _FakeSignal()

        def start(self):
            self.failed.emit("claude CLI が見つかりません。")

        def cancel(self):
            pass

        def is_cancelled(self):
            return False

        def isRunning(self):
            return False

        def wait(self):
            pass

    monkeypatch.setattr(mod, "_CoverDetectWorker", FailingWorker)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: shown.append(("critical", a[1])))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: shown.append(("info", a[1])))
    monkeypatch.setattr(QProgressDialog, "exec", lambda self: None)
    monkeypatch.setattr(QProgressDialog, "close", lambda self: None)

    d, _, _ = _dialog([], page_count=211)
    d._run_cover_detect()

    assert [kind for kind, _ in shown] == ["critical"], shown
