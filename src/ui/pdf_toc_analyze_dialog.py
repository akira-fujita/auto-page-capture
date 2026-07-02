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
    ClaudeTocEngine, ChapterRange, compute_offset, entries_to_chapters,
)
from src.export.pdf_splitter import PdfSplitter


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

        # ① 目次ページ範囲(inclusive)
        toc_group = QGroupBox("① 目次のPDFページ範囲(両端を含む)")
        toc_layout = QHBoxLayout(toc_group)
        self.toc_start_spin = QSpinBox(); self.toc_start_spin.setRange(1, max(1, n)); self.toc_start_spin.setPrefix("p.")
        self.toc_end_spin = QSpinBox(); self.toc_end_spin.setRange(1, max(1, n)); self.toc_end_spin.setPrefix("p.")
        self.toc_end_spin.setValue(min(2, n))
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
        anchor_row.addWidget(self.anchor_printed_spin); anchor_row.addWidget(QLabel("="))
        anchor_row.addWidget(self.anchor_pdf_spin); anchor_row.addStretch()
        anchor_outer.addLayout(anchor_row)
        self.anchor_example = QLabel(); self.anchor_example.setStyleSheet("color:#666;")
        anchor_outer.addWidget(self.anchor_example)
        layout.addWidget(anchor_group)

        self.preface_check = QCheckBox("最初の章より前のページを「前付け」として別章に残す")
        layout.addWidget(self.preface_check)

        self.analyze_btn = QPushButton("解析する")
        self.analyze_btn.clicked.connect(self._run_analyze)
        layout.addWidget(self.analyze_btn)

        self.summary_label = QLabel(); layout.addWidget(self.summary_label)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["章名", "→ PDFページ範囲"])
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
        self._sync_toc_end_min(self.toc_start_spin.value())
        self._update_labels()

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
            self._recompute()

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

    def _recompute(self):
        offset = compute_offset(self.anchor_pdf_spin.value(), self.anchor_printed_spin.value())
        ranges, warnings = entries_to_chapters(self._entries, offset, self.page_count)
        # 前付けオプション
        if self.preface_check.isChecked() and ranges and ranges[0].start > 0:
            ranges = [ChapterRange("前付け", 0, ranges[0].start - 1)] + ranges
        self.result_ranges = ranges
        self.warnings = warnings
        self._refresh_table()
        self.apply_btn.setEnabled(bool(ranges))

    def _refresh_table(self):
        self.table.setRowCount(len(self.result_ranges))
        for i, c in enumerate(self.result_ranges):
            self.table.setItem(i, 0, QTableWidgetItem(c.name))
            self.table.setItem(i, 1, QTableWidgetItem(f"p.{c.start + 1}-{c.end + 1}"))
        detected = len(self._entries)
        kept = len(self.result_ranges)
        self.summary_label.setText(
            f"目次から {detected} 件検出 → {kept} 章を作成。確定すると既存の章一覧は置き換えられます。"
        )
        self.warning_label.setText("\n".join(self.warnings))
