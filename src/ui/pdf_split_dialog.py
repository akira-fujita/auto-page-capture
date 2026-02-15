# src/ui/pdf_split_dialog.py
"""既存PDF章分割ダイアログUI"""

import subprocess
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QLineEdit, QPushButton, QSpinBox,
    QMessageBox, QGroupBox, QScrollArea,
    QFileDialog,
)
from PyQt6.QtCore import Qt

from src.ui.chapter_dialog import Chapter
from src.export.pdf_splitter import PdfSplitter


class _ChapterRow(QWidget):
    """章1行分の入力ウィジェット"""

    def __init__(self, index: int, name: str, start_page: int, max_page: int, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("章名")
        self.name_edit.setMinimumWidth(150)

        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, max_page)
        self.start_spin.setValue(start_page)
        self.start_spin.setPrefix("開始: p.")
        self.start_spin.setMinimumWidth(120)

        self.range_label = QLabel()
        self.range_label.setStyleSheet("color: #666; min-width: 100px;")

        self.delete_btn = QPushButton("削除")
        self.delete_btn.setFixedWidth(50)

        layout.addWidget(self.name_edit)
        layout.addWidget(self.start_spin)
        layout.addWidget(self.range_label)
        layout.addWidget(self.delete_btn)


class PdfSplitDialog(QDialog):
    """既存PDF章分割ダイアログ"""

    def __init__(self, pdf_path: Path, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.splitter = PdfSplitter()
        self.page_count = self.splitter.get_page_count(pdf_path)
        self._chapter_rows: list[_ChapterRow] = []

        self._init_ui()
        # 初期状態: 全ページを1章として
        self._add_chapter_row("第1章", 1)
        self._update_ranges()

    def _init_ui(self):
        """UIを初期化"""
        self.setWindowTitle(f"PDF分割 - {self.pdf_path.name}")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        # 説明文
        info = QLabel(
            f"{self.pdf_path.name}  ({self.page_count}ページ)\n"
            "各章の開始ページを指定してください。終了ページは次の章の直前まで自動計算されます。"
        )
        info.setStyleSheet("color: #666; margin-bottom: 8px;")
        layout.addWidget(info)

        # 章リスト
        chapter_group = QGroupBox("章一覧")
        chapter_outer = QVBoxLayout(chapter_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        self._rows_layout.addStretch()

        scroll.setWidget(self._rows_container)
        chapter_outer.addWidget(scroll)

        # 章追加ボタン
        add_btn = QPushButton("+ 章を追加")
        add_btn.clicked.connect(self._on_add_chapter)
        chapter_outer.addWidget(add_btn)

        layout.addWidget(chapter_group)

        # 出力先
        output_group = QGroupBox("出力先")
        output_layout = QHBoxLayout(output_group)

        self.output_edit = QLineEdit(str(self.pdf_path.parent))
        browse_btn = QPushButton("参照...")
        browse_btn.clicked.connect(self._browse_output)
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(browse_btn)

        layout.addWidget(output_group)

        # ボタン
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        split_btn = QPushButton("PDFを分割")
        split_btn.clicked.connect(self._do_split)
        split_btn.setDefault(True)
        button_layout.addWidget(split_btn)

        layout.addLayout(button_layout)

    def _add_chapter_row(self, name: str, start_page: int) -> _ChapterRow:
        """章の行を追加"""
        row = _ChapterRow(
            index=len(self._chapter_rows),
            name=name,
            start_page=start_page,
            max_page=self.page_count,
        )
        row.start_spin.valueChanged.connect(self._update_ranges)
        row.delete_btn.clicked.connect(lambda: self._remove_chapter_row(row))

        # stretch の手前に挿入
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
        self._chapter_rows.append(row)

        # 最初の章は削除不可
        self._chapter_rows[0].delete_btn.setEnabled(False)

        return row

    def _remove_chapter_row(self, row: _ChapterRow):
        """章の行を削除"""
        if row not in self._chapter_rows or len(self._chapter_rows) <= 1:
            return
        self._chapter_rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()
        self._chapter_rows[0].delete_btn.setEnabled(False)
        self._update_ranges()

    def _update_ranges(self):
        """各章のページ範囲ラベルを更新"""
        rows = sorted(self._chapter_rows, key=lambda r: r.start_spin.value())
        for i, row in enumerate(rows):
            start = row.start_spin.value()
            if i < len(rows) - 1:
                end = rows[i + 1].start_spin.value() - 1
            else:
                end = self.page_count

            if end < start:
                row.range_label.setText(f"→ 0ページ")
                row.range_label.setStyleSheet("color: #d32f2f; min-width: 100px;")
            else:
                row.range_label.setText(f"→ p.{start}-{end}")
                row.range_label.setStyleSheet("color: #666; min-width: 100px;")

    def _on_add_chapter(self):
        """章追加ボタン"""
        # 最後の章の開始ページ + 1 をデフォルトに
        if self._chapter_rows:
            last_start = max(r.start_spin.value() for r in self._chapter_rows)
            default_start = min(last_start + 1, self.page_count)
        else:
            default_start = 1
        num = len(self._chapter_rows) + 1
        self._add_chapter_row(f"第{num}章", default_start)
        self._update_ranges()

    def _build_chapters(self) -> list[Chapter] | None:
        """入力値からChapterリストを構築。バリデーションエラー時はNone"""
        rows = sorted(self._chapter_rows, key=lambda r: r.start_spin.value())

        # 開始ページの重複チェック（どの章が重複しているか明示）
        from collections import defaultdict
        page_to_names: dict[int, list[str]] = defaultdict(list)
        for row in rows:
            name = row.name_edit.text().strip() or "(名称未設定)"
            page_to_names[row.start_spin.value()].append(name)

        duplicates = {page: names for page, names in page_to_names.items() if len(names) > 1}
        if duplicates:
            lines = []
            for page, names in sorted(duplicates.items()):
                names_str = "、".join(f"「{n}」" for n in names)
                lines.append(f"  p.{page}: {names_str}")
            detail = "\n".join(lines)
            QMessageBox.warning(
                self, "開始ページの重複",
                f"以下の章で開始ページが重複しています:\n\n{detail}\n\n"
                "開始ページを修正してください。"
            )
            return None

        chapters = []
        for i, row in enumerate(rows):
            start = row.start_spin.value() - 1  # 0-indexed
            if i < len(rows) - 1:
                end = rows[i + 1].start_spin.value() - 2  # 0-indexed, inclusive
            else:
                end = self.page_count - 1
            name = row.name_edit.text().strip() or f"第{i + 1}章"
            chapters.append(Chapter(name=name, start=start, end=end))

        return chapters

    def _browse_output(self):
        """出力先ディレクトリを選択"""
        path = QFileDialog.getExistingDirectory(self, "出力先を選択")
        if path:
            self.output_edit.setText(path)

    def _do_split(self):
        """PDFを分割"""
        chapters = self._build_chapters()
        if chapters is None:
            return

        output_dir = Path(self.output_edit.text())
        if not output_dir.exists():
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, "エラー", f"出力先を作成できません:\n{e}")
                return

        try:
            output_paths = self.splitter.split(self.pdf_path, chapters, output_dir)

            file_list = "\n".join(f"  - {p.name}" for p in output_paths)
            QMessageBox.information(
                self,
                "完了",
                f"PDFを分割しました。\n\n"
                f"出力先: {output_dir}\n\n"
                f"ファイル:\n{file_list}"
            )

            subprocess.Popen(["open", str(output_dir)])
            self.accept()

        except Exception as e:
            QMessageBox.critical(
                self,
                "エラー",
                f"PDF分割中にエラーが発生しました:\n{str(e)}"
            )
