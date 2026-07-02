"""既存PDFの目次を解析して章範囲を提案するダイアログ"""

import tempfile
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QCheckBox,
    QPushButton, QGroupBox, QTableWidget, QTableWidgetItem,
    QMessageBox, QApplication,
)
from PyQt6.QtCore import Qt

from src.export.toc_analyzer import (
    ClaudeTocEngine, ChapterRange, compute_offset, entries_to_chapters, is_chapter,
)
from src.export.pdf_splitter import PdfSplitter


_TOC_HELP_TEXT = (
    "目次ページを読み取って、章の開始ページを自動入力する機能です。\n\n"
    "手順:\n"
    "1. ① 目次のPDFページ範囲 — 目次が載っているPDFのページを指定（両端を含む）。\n"
    "2. ② ページ番号アンカー — 目次で「1ページ」と書かれた本文が、PDFでは何ページ目か"
    "を指定。印刷ページとPDFページのズレを1点で補正します。\n"
    "3. 必要なら「最初の章より前を前付けとして残す」をチェック。\n"
    "4.「解析する」を押すと、章名とページ範囲の候補が表に出ます"
    "（前付けのローマ数字ページは自動で別扱い）。\n"
    "5. 出力したい章だけチェック。「章のみ」で部見出し・参考文献・索引を一括で外せます。\n"
    "6.「この内容で章を設定」で分割画面に反映します。"
)


class PdfTocAnalyzeDialog(QDialog):
    """既存PDFの目次から章を自動解析するダイアログ"""

    def __init__(self, pdf_path: Path, page_count: int, engine=None, splitter=None, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.page_count = page_count
        self.engine = engine or ClaudeTocEngine()
        self.splitter = splitter or PdfSplitter()
        self._entries = []
        self.result_ranges = []
        self.warnings = []
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("目次から章を自動解析")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        n = self.page_count

        # ヘッダ（使い方ボタン）
        header = QHBoxLayout()
        header.addStretch()
        self.help_btn = QPushButton("❓ 使い方")
        self.help_btn.setToolTip("この画面の使い方（手順）を表示します")
        self.help_btn.clicked.connect(self._show_help)
        header.addWidget(self.help_btn)
        layout.addLayout(header)

        # ① 目次ページ範囲(inclusive)
        toc_group = QGroupBox("① 目次のPDFページ範囲(両端を含む)")
        toc_layout = QHBoxLayout(toc_group)
        self.toc_start_spin = QSpinBox(); self.toc_start_spin.setRange(1, max(1, n)); self.toc_start_spin.setPrefix("p.")
        self.toc_end_spin = QSpinBox(); self.toc_end_spin.setRange(1, max(1, n)); self.toc_end_spin.setPrefix("p.")
        self.toc_end_spin.setValue(min(2, n))
        self.toc_start_spin.setToolTip("目次が載っているPDFの先頭ページ（表紙から数えた実際のページ番号）")
        self.toc_end_spin.setToolTip("目次が載っているPDFの最終ページ（両端を含む）")
        self.toc_count_label = QLabel()
        toc_layout.addWidget(self.toc_start_spin); toc_layout.addWidget(QLabel("〜"))
        toc_layout.addWidget(self.toc_end_spin); toc_layout.addWidget(self.toc_count_label)
        toc_layout.addStretch()
        layout.addWidget(toc_group)

        # ② アンカー
        anchor_group = QGroupBox("② ページ番号アンカー(ズレ補正)")
        anchor_outer = QVBoxLayout(anchor_group)
        anchor_row = QHBoxLayout()
        self.anchor_printed_spin = QSpinBox(); self.anchor_printed_spin.setRange(1, 99999); self.anchor_printed_spin.setPrefix("印刷 p.")
        self.anchor_pdf_spin = QSpinBox(); self.anchor_pdf_spin.setRange(1, max(1, n)); self.anchor_pdf_spin.setPrefix("PDF #")
        self.anchor_printed_spin.setToolTip(
            "本文に『ページ番号』として印刷されている数字（目次に載る番号）。\n"
            "例: 本文が 1 から始まるなら 1。"
        )
        self.anchor_pdf_spin.setToolTip(
            "上の印刷ページが、PDFでは何ページ目にあたるか。\n"
            "印刷ページとPDFページのズレをこの1点で補正します。"
        )
        anchor_row.addWidget(self.anchor_printed_spin); anchor_row.addWidget(QLabel("="))
        anchor_row.addWidget(self.anchor_pdf_spin); anchor_row.addStretch()
        anchor_outer.addLayout(anchor_row)
        self.anchor_example = QLabel(); self.anchor_example.setStyleSheet("color:#666;")
        anchor_outer.addWidget(self.anchor_example)
        layout.addWidget(anchor_group)

        self.preface_check = QCheckBox("最初の章より前のページを「前付け」として別章に残す")
        self.preface_check.setToolTip(
            "最初の章より前（表紙・まえがき等）を『前付け』として1章にまとめて残します。"
        )
        layout.addWidget(self.preface_check)

        self.analyze_btn = QPushButton("解析する")
        self.analyze_btn.setToolTip(
            "指定した目次ページを画像化し、claude CLI で章名とページ番号を読み取ります。"
        )
        self.analyze_btn.clicked.connect(self._run_analyze)
        layout.addWidget(self.analyze_btn)

        self.summary_label = QLabel(); layout.addWidget(self.summary_label)

        # 出力対象の選別ボタン
        select_row = QHBoxLayout()
        self.chapter_only_btn = QPushButton("章のみ")
        self.select_all_btn = QPushButton("全選択")
        self.select_none_btn = QPushButton("全解除")
        self.chapter_only_btn.setToolTip(
            "章の行（例: 第1章 / 9章 / 序章・終章 / Chapter 1）だけチェックし、"
            "部見出し・参考文献・索引などを出力対象から外します。"
        )
        self.select_all_btn.setToolTip("すべての行を出力対象にします。")
        self.select_none_btn.setToolTip("すべての行の出力対象を外します。")
        self.chapter_only_btn.clicked.connect(self._on_chapter_only)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        for b in (self.chapter_only_btn, self.select_all_btn, self.select_none_btn):
            select_row.addWidget(b)
        select_row.addStretch()
        layout.addLayout(select_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["出力", "章名", "→ PDFページ範囲"])
        self.table.setToolTip("チェックした章だけが出力対象になります。")
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)
        self.warning_label = QLabel(); self.warning_label.setStyleSheet("color:#d32f2f;"); self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)

        btns = QHBoxLayout(); btns.addStretch()
        cancel = QPushButton("キャンセル"); cancel.clicked.connect(self.reject); btns.addWidget(cancel)
        self.apply_btn = QPushButton("この内容で章を設定(既存の行は置換されます)")
        self.apply_btn.clicked.connect(self.accept); self.apply_btn.setEnabled(False); btns.addWidget(self.apply_btn)
        layout.addLayout(btns)

        # ライブ更新
        self.toc_start_spin.valueChanged.connect(self._update_labels)
        self.toc_start_spin.valueChanged.connect(self._sync_toc_end_min)
        self.toc_end_spin.valueChanged.connect(self._update_labels)
        self.anchor_printed_spin.valueChanged.connect(self._on_anchor_changed)
        self.anchor_pdf_spin.valueChanged.connect(self._on_anchor_changed)
        self.preface_check.toggled.connect(self._on_preface_toggled)
        self._sync_toc_end_min(self.toc_start_spin.value())
        self._update_labels()

    def _show_help(self):
        QMessageBox.information(self, "使い方 — 目次から章を自動解析", _TOC_HELP_TEXT)

    def _sync_toc_end_min(self, start_value: int):
        self.toc_end_spin.setMinimum(start_value)

    def _update_labels(self):
        start, end = self.toc_start_spin.value(), self.toc_end_spin.value()
        count = max(0, end - start + 1)
        self.toc_count_label.setText(f"（{count}ページを解析）")
        offset = compute_offset(self.anchor_pdf_spin.value(), self.anchor_printed_spin.value())
        self.anchor_example.setText(
            f"例: 印刷 p.{self.anchor_printed_spin.value()} は PDF の {self.anchor_pdf_spin.value()} ページ目 "
            f"(ズレ offset={offset:+d})"
        )

    def _on_anchor_changed(self, _v):
        self._update_labels()
        if self._entries:
            self._recompute(reset_selection=False)

    def _on_preface_toggled(self, _checked: bool):
        if self._entries:
            self._recompute(reset_selection=False)

    def _selected_page_indices(self) -> list[int]:
        start = self.toc_start_spin.value()
        end = max(self.toc_end_spin.value(), start)
        return [p - 1 for p in range(start, end + 1)]  # 0始まりindex, inclusive

    def _run_analyze(self):
        indices = self._selected_page_indices()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                paths = []
                for idx in indices:
                    out = Path(tmp) / f"toc_{idx}.png"
                    self.splitter.render_page_image(self.pdf_path, idx, out)
                    paths.append(out)
                self._entries = self.engine.analyze(paths)
        except FileNotFoundError:
            self._reset_state()
            QMessageBox.critical(self, "エラー", "claude CLI が見つかりませんでした。手動でページを入力してください。")
            return
        except Exception as e:
            self._reset_state()
            QMessageBox.critical(self, "エラー", f"目次の解析に失敗しました:\n{e}\n\n手動でページを入力してください。")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._recompute()

    def _reset_state(self):
        self._entries = []
        self.result_ranges = []
        self.warnings = []
        self._refresh_table()
        self.apply_btn.setEnabled(False)

    def _recompute(self, reset_selection: bool = True):
        offset = compute_offset(self.anchor_pdf_spin.value(), self.anchor_printed_spin.value())
        ranges, warnings = entries_to_chapters(self._entries, offset, self.page_count)
        # 前付けオプション
        if self.preface_check.isChecked() and ranges and ranges[0].start > 0:
            ranges = [ChapterRange("前付け", 0, ranges[0].start - 1)] + ranges
        self.result_ranges = ranges
        self.warnings = warnings
        self._refresh_table(reset_selection=reset_selection)

    @property
    def selected_ranges(self) -> list[ChapterRange]:
        """チェックされている行に対応する ChapterRange をテーブル順で返す。"""
        selected = []
        for i, c in enumerate(self.result_ranges):
            item = self.table.item(i, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                selected.append(c)
        return selected

    def _refresh_table(self, reset_selection: bool = True):
        # 再計算(アンカー/前付け変更)では選択状態を保持する。名前ごとに以前の
        # チェック状態を出現順で控え、同名行も位置で区別する。新規名はチェック済み。
        prior: dict[str, list[bool]] = {}
        if not reset_selection:
            for i in range(self.table.rowCount()):
                name_item = self.table.item(i, 1)
                if name_item is None:
                    continue
                checked = self.table.item(i, 0).checkState() == Qt.CheckState.Checked
                prior.setdefault(name_item.text(), []).append(checked)

        # 行を作り直す間は itemChanged が誤発火しないようブロックする
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.result_ranges))
        consumed: dict[str, int] = {}
        for i, c in enumerate(self.result_ranges):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            if reset_selection:
                keep = True
            else:
                states = prior.get(c.name)
                idx = consumed.get(c.name, 0)
                # 既知の名前は出現順で対応、未知/超過分はチェック済み(新規扱い)
                keep = states[idx] if states is not None and idx < len(states) else True
                consumed[c.name] = idx + 1
            check.setCheckState(Qt.CheckState.Checked if keep else Qt.CheckState.Unchecked)
            self.table.setItem(i, 0, check)
            self.table.setItem(i, 1, QTableWidgetItem(c.name))
            self.table.setItem(i, 2, QTableWidgetItem(f"p.{c.start + 1}-{c.end + 1}"))
        self.table.blockSignals(False)
        self.warning_label.setText("\n".join(self.warnings))
        self._update_selection_ui()

    def _update_selection_ui(self):
        """サマリ表示と Apply ボタン活性を選択状態に追従させる。"""
        detected = len(self._entries)
        selected = len(self.selected_ranges)
        self.summary_label.setText(
            f"目次から {detected} 件検出 → {selected} 章を出力対象。"
            "確定すると既存の章一覧は置き換えられます。"
        )
        self.apply_btn.setEnabled(selected > 0)

    def _on_item_changed(self, _item):
        self._update_selection_ui()

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            self.table.item(i, 0).setCheckState(state)
        self.table.blockSignals(False)
        self._update_selection_ui()

    def _on_chapter_only(self):
        """「章」と判定できる行だけをチェックする。0件一致なら警告して状態維持。"""
        matches = [i for i, c in enumerate(self.result_ranges) if is_chapter(c.name)]
        if not matches:
            QMessageBox.information(
                self, "章が見つかりません",
                "章として判定できる見出しがありませんでした。手動で選択してください。",
            )
            return
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            state = Qt.CheckState.Checked if i in matches else Qt.CheckState.Unchecked
            self.table.item(i, 0).setCheckState(state)
        self.table.blockSignals(False)
        self._update_selection_ui()
