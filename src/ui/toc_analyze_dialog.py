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
        self.anchor_printed_spin.valueChanged.connect(self._on_anchor_changed)
        self.anchor_capture_spin.valueChanged.connect(self._on_anchor_changed)

        # 解析ボタン
        self.analyze_btn = QPushButton("解析する")
        self.analyze_btn.clicked.connect(self._run_analyze)
        layout.addWidget(self.analyze_btn)

        # ③ プレビュー
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["章名", "→ キャプチャ範囲"])
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
            self._entries = []
            self.result_ranges = []
            self.warnings = []
            self._refresh_table()
            self.apply_btn.setEnabled(False)
            QMessageBox.critical(
                self, "エラー",
                "claude CLI が見つかりませんでした。手動でページを入力してください。",
            )
            return
        except Exception as e:  # タイムアウト・JSON不可など
            QApplication.restoreOverrideCursor()
            self._entries = []
            self.result_ranges = []
            self.warnings = []
            self._refresh_table()
            self.apply_btn.setEnabled(False)
            QMessageBox.critical(
                self, "エラー",
                f"目次の解析に失敗しました:\n{e}\n\n手動でページを入力してください。",
            )
            return
        QApplication.restoreOverrideCursor()
        self._recompute()

    def _on_anchor_changed(self, _value: int):
        if self._entries:
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
            self.table.setItem(i, 1, QTableWidgetItem(f"p.{c.start + 1}-{c.end + 1}"))
        self.warning_label.setText("\n".join(self.warnings))
