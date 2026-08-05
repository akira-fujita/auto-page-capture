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
from src.export.toc_analyzer import ChapterRange


_SPLIT_HELP_TEXT = (
    "PDFを章ごとに分割する画面です。\n\n"
    "手順:\n"
    "1.「目次から章を自動解析」で章の開始ページを自動入力（おすすめ）。"
    "手動なら「+ 章を追加」。\n"
    "2. 各行で章名と開始ページを調整。終了ページは次の章の直前まで自動、"
    "または目次解析で決まった終了ページになります。\n"
    "3.「出力されないページ」に、どの章にも含まれないページ（前付け・部の扉・"
    "参考文献・索引など）が出ます。ここに出たページは分割PDFに含まれません。\n"
    "4. 出力先を確認し「PDFを分割」を実行。章ごとにPDFが書き出されます。"
)


def excluded_page_ranges(spans: list[tuple[int, int]], total_pages: int) -> list[tuple[int, int]]:
    """章に含まれないページ範囲を求める。

    spans: 各章の (start, end) 0始まり包含。total_pages: 総ページ数。
    戻り値: 除外ページの (start, end) を1始まり包含で、昇順に返す。
    """
    covered = set()
    for start, end in spans:
        for p in range(max(0, start), min(total_pages, end + 1)):
            covered.add(p)
    ranges: list[tuple[int, int]] = []
    run_start = None
    for p in range(total_pages):
        if p not in covered:
            if run_start is None:
                run_start = p
        else:
            if run_start is not None:
                ranges.append((run_start + 1, p))  # 1始まり包含
                run_start = None
    if run_start is not None:
        ranges.append((run_start + 1, total_pages))
    return ranges


class _ChapterRow(QWidget):
    """章1行分の入力ウィジェット"""

    def __init__(self, index: int, name: str, start_page: int, max_page: int,
                 end_page: int | None = None, parent=None):
        super().__init__(parent)
        # TOC 解析由来の明示的な終了ページ(1始まり, inclusive)。None なら次章直前まで
        # 自動計算する従来の連続モデル。除外行のギャップを保持するために使う。
        self.explicit_end = end_page
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("章名")
        self.name_edit.setMinimumWidth(150)
        self.name_edit.setToolTip("章名（出力するPDFのファイル名に使われます）")

        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, max_page)
        self.start_spin.setValue(start_page)
        self.start_spin.setPrefix("開始: p.")
        self.start_spin.setMinimumWidth(120)
        self.start_spin.setToolTip(
            "この章の開始ページ（PDFのページ番号）。\n"
            "終了ページは次の章の直前まで自動、または目次解析で決まった終了ページ。"
        )

        self.range_label = QLabel()
        self.range_label.setStyleSheet("color: #666; min-width: 100px;")

        self.delete_btn = QPushButton("削除")
        self.delete_btn.setFixedWidth(50)
        self.delete_btn.setToolTip("この章の行を削除します")

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

        # ヘッダ（ファイル情報 ＋ 使い方ボタン）
        header = QHBoxLayout()
        info = QLabel(
            f"{self.pdf_path.name}  ({self.page_count}ページ)\n"
            "各章の開始ページを指定してください。終了ページは次の章の直前まで自動、"
            "または目次解析で決まった終了ページになります。"
        )
        info.setStyleSheet("color: #666; margin-bottom: 8px;")
        header.addWidget(info)
        header.addStretch()
        self.help_btn = QPushButton("❓ 使い方")
        self.help_btn.setToolTip("この画面の使い方（手順）を表示します")
        self.help_btn.clicked.connect(self._show_help)
        header.addWidget(self.help_btn)
        layout.addLayout(header)

        self.toc_btn = QPushButton("目次から章を自動解析")
        self.toc_btn.setToolTip("目次ページを解析して、章名と開始ページを自動入力します。")
        self.toc_btn.clicked.connect(self._open_toc_analyze)
        layout.addWidget(self.toc_btn)

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
        add_btn.setToolTip("章の行を手動で追加します。")
        add_btn.clicked.connect(self._on_add_chapter)
        chapter_outer.addWidget(add_btn)

        layout.addWidget(chapter_group)

        # 除外されるページ（どの章にも含まれないページ）の表示
        self.excluded_label = QLabel()
        self.excluded_label.setWordWrap(True)
        self.excluded_label.setStyleSheet("color: #d32f2f; margin: 2px 0;")
        layout.addWidget(self.excluded_label)

        # 出力先
        output_group = QGroupBox("出力先")
        output_layout = QHBoxLayout(output_group)

        self.output_edit = QLineEdit(str(self.pdf_path.parent))
        self.output_edit.setToolTip("分割したPDFの出力先フォルダ。実行時にタイムスタンプ付きサブフォルダを作成します。")
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

        self.split_btn = QPushButton("PDFを分割")
        self.split_btn.setToolTip("各章を個別のPDFに書き出します。")
        self.split_btn.clicked.connect(self._do_split)
        self.split_btn.setDefault(True)
        button_layout.addWidget(self.split_btn)

        layout.addLayout(button_layout)

    def _show_help(self):
        QMessageBox.information(self, "使い方 — PDF分割", _SPLIT_HELP_TEXT)

    def _add_chapter_row(self, name: str, start_page: int, end_page: int | None = None) -> _ChapterRow:
        """章の行を追加。end_page を渡すと終了ページを固定（除外行のギャップ保持用）"""
        row = _ChapterRow(
            index=len(self._chapter_rows),
            name=name,
            start_page=start_page,
            max_page=self.page_count,
            end_page=end_page,
        )
        # 開始ページを手動変更したら固定終了を解除し従来の連続モデルに戻す
        row.start_spin.valueChanged.connect(lambda _v, r=row: setattr(r, "explicit_end", None))
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

    def _row_end(self, row: _ChapterRow, rows: list, i: int) -> int:
        """行の終了ページ(1始まり, inclusive)。明示的 end があればそれを、
        なければ次章直前まで（最終章は最終ページ）を返す。

        明示的 end は必ず「次章の開始直前」を上限にクランプする。これにより
        隣の行の開始を手前に動かしても章範囲が重複しない（ギャップは保持）。"""
        start = row.start_spin.value()
        # 連続モデルでの上限（次章の直前 / 最終章は最終ページ）
        contiguous = rows[i + 1].start_spin.value() - 1 if i < len(rows) - 1 else self.page_count
        if row.explicit_end is not None and row.explicit_end >= start:
            return min(row.explicit_end, contiguous, self.page_count)
        return contiguous

    def _update_ranges(self):
        """各章のページ範囲ラベルと、除外ページのサマリを更新"""
        rows = sorted(self._chapter_rows, key=lambda r: r.start_spin.value())
        spans: list[tuple[int, int]] = []
        for i, row in enumerate(rows):
            start = row.start_spin.value()
            end = self._row_end(row, rows, i)

            if end < start:
                row.range_label.setText(f"→ 0ページ")
                row.range_label.setStyleSheet("color: #d32f2f; min-width: 100px;")
            else:
                row.range_label.setText(f"→ p.{start}-{end}")
                row.range_label.setStyleSheet("color: #666; min-width: 100px;")
                spans.append((start - 1, end - 1))  # 0始まり包含

        self._update_excluded_label(spans)

    def _update_excluded_label(self, spans: list[tuple[int, int]]):
        excluded = excluded_page_ranges(spans, self.page_count)
        if not excluded:
            self.excluded_label.setText("すべてのページがいずれかの章に含まれます。")
            self.excluded_label.setStyleSheet("color: #666; margin: 2px 0;")
            return
        total = sum(e - s + 1 for s, e in excluded)
        parts = ", ".join(f"p.{s}" if s == e else f"p.{s}-{e}" for s, e in excluded)
        self.excluded_label.setText(f"⚠ 出力されないページ: {parts}（計{total}ページ）")
        self.excluded_label.setStyleSheet("color: #d32f2f; margin: 2px 0;")

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

    def _open_toc_analyze(self):
        """目次解析ダイアログを開き、確定したら章行を置換"""
        from src.ui.pdf_toc_analyze_dialog import PdfTocAnalyzeDialog
        dialog = PdfTocAnalyzeDialog(self.pdf_path, self.page_count, parent=self)
        if dialog.exec() and dialog.selected_ranges:
            self._apply_toc_ranges(dialog.selected_ranges)

    def _apply_toc_ranges(self, ranges: list[ChapterRange]):
        """解析結果で章行を全置換する（start は0始まり→1始まりの開始ページへ）"""
        # 既存行を全消去
        for row in list(self._chapter_rows):
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._chapter_rows.clear()
        # 新規行を生成（start/end を明示指定し、除外行のギャップを保持する）
        for r in ranges:
            self._add_chapter_row(r.name, r.start + 1, r.end + 1)
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
            end = self._row_end(row, rows, i) - 1  # 0-indexed, inclusive
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
            # 既存ファイルとの衝突を避けるため、毎回タイムスタンプ付きサブフォルダを作る
            split_dir = self.splitter.file_manager.create_split_output_directory(
                output_dir, self.pdf_path.stem
            )
            output_paths = self.splitter.split(self.pdf_path, chapters, split_dir)

            file_list = "\n".join(f"  - {p.name}" for p in output_paths)
            QMessageBox.information(
                self,
                "完了",
                f"PDFを分割しました。\n\n"
                f"出力先: {split_dir}\n\n"
                f"ファイル:\n{file_list}"
            )

            subprocess.Popen(["open", str(split_dir)])
            self.accept()

        except Exception as e:
            QMessageBox.critical(
                self,
                "エラー",
                f"PDF分割中にエラーが発生しました:\n{str(e)}"
            )
