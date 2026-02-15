# src/ui/chapter_dialog.py
"""章分割ダイアログUI"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea, QWidget,
    QLabel, QLineEdit, QPushButton, QCheckBox, QListWidget,
    QListWidgetItem, QFrame, QMessageBox, QGroupBox, QSplitter,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from src.export.pdf_generator import PdfGenerator
from src.export.file_manager import FileManager


@dataclass
class Chapter:
    """章情報"""
    name: str
    start: int  # 0-indexed
    end: int    # 0-indexed, inclusive


class ThumbnailWidget(QFrame):
    """サムネイル表示ウィジェット"""

    clicked = pyqtSignal(int)

    def __init__(self, image_path: Path | None, index: int, *, pixmap: QPixmap | None = None, parent=None):
        super().__init__(parent)
        self.index = index
        self.image_path = image_path
        self._source_pixmap = pixmap
        self._is_chapter_start = False

        self._init_ui()

    def _init_ui(self):
        """UIを初期化"""
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Plain)
        self.setLineWidth(2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # サムネイル画像
        self.image_label = QLabel()
        if self._source_pixmap is not None:
            pixmap = self._source_pixmap
        else:
            pixmap = QPixmap(str(self.image_path))
        scaled = pixmap.scaled(
            100, 140,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.image_label.setPixmap(scaled)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_label)

        # ページ番号
        self.page_label = QLabel(f"p.{self.index + 1}")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.page_label)

        self._update_style()

    def _update_style(self):
        """スタイルを更新"""
        if self._is_chapter_start:
            self.setStyleSheet("""
                ThumbnailWidget {
                    background-color: #e3f2fd;
                    border: 2px solid #1976d2;
                }
            """)
        else:
            self.setStyleSheet("""
                ThumbnailWidget {
                    background-color: #ffffff;
                    border: 1px solid #cccccc;
                }
                ThumbnailWidget:hover {
                    background-color: #f5f5f5;
                    border: 1px solid #999999;
                }
            """)

    def set_chapter_start(self, is_start: bool):
        """章の開始位置かどうかを設定"""
        self._is_chapter_start = is_start
        self._update_style()

    def mousePressEvent(self, event):
        """クリックイベント"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)


class ChapterDialog(QDialog):
    """章分割ダイアログ"""

    def __init__(
        self,
        image_paths: list[Path],
        output_dir: Path,
        keep_images: bool,
        parent=None
    ):
        super().__init__(parent)
        self.image_paths = image_paths
        self.output_dir = output_dir
        self.keep_images = keep_images
        self.pdf_generator = PdfGenerator()
        self.file_manager = FileManager()

        self.chapters: list[Chapter] = []
        self.thumbnails: list[ThumbnailWidget] = []
        self._current_chapter_row = -1

        # 初期章を作成（全ページを1章として）
        if image_paths:
            self.chapters.append(Chapter(
                name="第1章",
                start=0,
                end=len(image_paths) - 1
            ))

        self._init_ui()
        self._update_thumbnails()
        self._update_chapter_list()

    def _init_ui(self):
        """UIを初期化"""
        self.setWindowTitle("章分割とPDF出力")
        self.setMinimumSize(900, 600)

        layout = QVBoxLayout(self)

        # 説明文
        instruction = QLabel(
            "サムネイルをクリックすると、その位置から新しい章が始まります。\n"
            "章を選択して名前を編集したり、削除したりできます。"
        )
        instruction.setStyleSheet("color: #666; margin-bottom: 10px;")
        layout.addWidget(instruction)

        # メインエリア（スプリッター）
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左側: サムネイル一覧
        thumbnail_group = QGroupBox("ページ一覧")
        thumbnail_layout = QVBoxLayout(thumbnail_group)

        # スクロールエリア
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setMinimumHeight(200)

        # サムネイルコンテナ
        self.thumbnail_container = QWidget()
        self.thumbnail_layout = QHBoxLayout(self.thumbnail_container)
        self.thumbnail_layout.setContentsMargins(8, 8, 8, 8)
        self.thumbnail_layout.setSpacing(8)
        self.thumbnail_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.scroll_area.setWidget(self.thumbnail_container)
        thumbnail_layout.addWidget(self.scroll_area)

        splitter.addWidget(thumbnail_group)

        # 右側: 章リストと編集
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # 章リスト
        chapter_group = QGroupBox("章一覧")
        chapter_layout = QVBoxLayout(chapter_group)

        self.chapter_list = QListWidget()
        self.chapter_list.currentRowChanged.connect(self._on_chapter_selected)
        chapter_layout.addWidget(self.chapter_list)

        # 章名編集
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("章名:"))
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_name_changed)
        self.name_edit.setEnabled(False)
        name_layout.addWidget(self.name_edit)
        chapter_layout.addLayout(name_layout)

        # 削除ボタン
        self.delete_btn = QPushButton("選択した章を削除")
        self.delete_btn.clicked.connect(self._delete_chapter)
        self.delete_btn.setEnabled(False)
        chapter_layout.addWidget(self.delete_btn)

        right_layout.addWidget(chapter_group)

        # 出力オプション
        output_group = QGroupBox("出力オプション")
        output_layout = QVBoxLayout(output_group)

        self.merge_check = QCheckBox("全ページを1つのPDFにまとめる")
        self.merge_check.setChecked(True)
        output_layout.addWidget(self.merge_check)

        self.chapter_pdf_check = QCheckBox("章ごとにPDFを作成する")
        self.chapter_pdf_check.setChecked(False)
        output_layout.addWidget(self.chapter_pdf_check)

        right_layout.addWidget(output_group)

        splitter.addWidget(right_widget)
        splitter.setSizes([600, 300])

        layout.addWidget(splitter)

        # ボタン
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        self.export_btn = QPushButton("PDFを出力")
        self.export_btn.clicked.connect(self._export_pdfs)
        self.export_btn.setDefault(True)
        button_layout.addWidget(self.export_btn)

        layout.addLayout(button_layout)

    def _on_thumbnail_clicked(self, index: int):
        """サムネイルがクリックされた"""
        # 最初のページは常に章の開始なので変更不可
        if index == 0:
            return

        # 既存の章の開始位置かどうかチェック
        existing_chapter_idx = None
        for i, chapter in enumerate(self.chapters):
            if chapter.start == index:
                existing_chapter_idx = i
                break

        if existing_chapter_idx is not None:
            # 既存の章を削除（前の章と統合）
            if existing_chapter_idx > 0:
                # 前の章の終了位置を更新
                self.chapters[existing_chapter_idx - 1].end = \
                    self.chapters[existing_chapter_idx].end
                del self.chapters[existing_chapter_idx]
        else:
            # 新しい章を作成
            # どの章の中間点かを見つける
            for i, chapter in enumerate(self.chapters):
                if chapter.start < index <= chapter.end:
                    # この章を分割
                    new_chapter = Chapter(
                        name=f"第{len(self.chapters) + 1}章",
                        start=index,
                        end=chapter.end
                    )
                    chapter.end = index - 1
                    self.chapters.insert(i + 1, new_chapter)
                    break

        self._recalculate_chapter_ranges()
        self._update_chapter_list()
        self._update_thumbnails()

    def _recalculate_chapter_ranges(self):
        """章の範囲を再計算"""
        # 章を開始位置でソート
        self.chapters.sort(key=lambda c: c.start)

        # 範囲を再計算
        for i, chapter in enumerate(self.chapters):
            if i < len(self.chapters) - 1:
                chapter.end = self.chapters[i + 1].start - 1
            else:
                chapter.end = len(self.image_paths) - 1

    def _update_chapter_list(self):
        """章リストを更新"""
        self.chapter_list.clear()
        for chapter in self.chapters:
            page_range = f"p.{chapter.start + 1}-{chapter.end + 1}"
            item = QListWidgetItem(f"{chapter.name} ({page_range})")
            self.chapter_list.addItem(item)

    def _update_thumbnails(self):
        """サムネイル表示を更新"""
        # 既存のサムネイルをクリア
        for thumb in self.thumbnails:
            thumb.deleteLater()
        self.thumbnails.clear()

        # 章の開始位置を集める
        chapter_starts = {chapter.start for chapter in self.chapters}

        # サムネイルを作成
        for i, path in enumerate(self.image_paths):
            thumb = ThumbnailWidget(path, i)
            thumb.set_chapter_start(i in chapter_starts)
            thumb.clicked.connect(self._on_thumbnail_clicked)
            self.thumbnail_layout.addWidget(thumb)
            self.thumbnails.append(thumb)

    def _on_chapter_selected(self, row: int):
        """章が選択された"""
        self._current_chapter_row = row
        if row >= 0 and row < len(self.chapters):
            chapter = self.chapters[row]
            self.name_edit.setEnabled(True)
            self.name_edit.setText(chapter.name)
            # 最初の章は削除不可
            self.delete_btn.setEnabled(row > 0)

            # 対応するサムネイルにスクロール
            if chapter.start < len(self.thumbnails):
                thumb = self.thumbnails[chapter.start]
                self.scroll_area.ensureWidgetVisible(thumb)
        else:
            self.name_edit.setEnabled(False)
            self.name_edit.clear()
            self.delete_btn.setEnabled(False)

    def _on_name_changed(self, text: str):
        """章名が変更された"""
        if self._current_chapter_row >= 0:
            self.chapters[self._current_chapter_row].name = text
            # リスト表示を更新
            chapter = self.chapters[self._current_chapter_row]
            page_range = f"p.{chapter.start + 1}-{chapter.end + 1}"
            item = self.chapter_list.item(self._current_chapter_row)
            if item:
                item.setText(f"{chapter.name} ({page_range})")

    def _delete_chapter(self):
        """選択した章を削除"""
        row = self._current_chapter_row
        if row <= 0 or row >= len(self.chapters):
            return

        # 前の章と統合
        self.chapters[row - 1].end = self.chapters[row].end
        del self.chapters[row]

        self._recalculate_chapter_ranges()
        self._update_chapter_list()
        self._update_thumbnails()

        # 選択をクリア
        self._current_chapter_row = -1
        self.name_edit.setEnabled(False)
        self.name_edit.clear()
        self.delete_btn.setEnabled(False)

    def _export_pdfs(self):
        """PDFを出力"""
        if not self.merge_check.isChecked() and not self.chapter_pdf_check.isChecked():
            QMessageBox.warning(
                self,
                "エラー",
                "少なくとも1つの出力オプションを選択してください。"
            )
            return

        try:
            exported_files = []

            # 全ページを1つのPDFにまとめる
            if self.merge_check.isChecked():
                merged_path = self.output_dir / "merged.pdf"
                self.pdf_generator.generate(self.image_paths, merged_path)
                exported_files.append(merged_path)

            # 章ごとにPDFを作成
            if self.chapter_pdf_check.isChecked():
                for i, chapter in enumerate(self.chapters):
                    chapter_images = self.image_paths[chapter.start:chapter.end + 1]
                    pdf_path = self.file_manager.get_chapter_pdf_path(
                        self.output_dir, i + 1, chapter.name
                    )
                    self.pdf_generator.generate(chapter_images, pdf_path)
                    exported_files.append(pdf_path)

            # 元画像を削除
            if not self.keep_images:
                self.file_manager.cleanup_images(self.output_dir)

            # 完了メッセージ
            file_list = "\n".join(f"  - {p.name}" for p in exported_files)
            QMessageBox.information(
                self,
                "完了",
                f"PDFを出力しました。\n\n出力先: {self.output_dir}\n\nファイル:\n{file_list}"
            )

            # デスクトップ通知
            from src.utils.notification import send_notification
            send_notification(
                "Kindle Page Capture",
                f"PDF出力完了: {len(exported_files)}ファイル"
            )

            # 出力フォルダをFinderで開く
            subprocess.Popen(["open", str(self.output_dir)])

            self.accept()

        except Exception as e:
            QMessageBox.critical(
                self,
                "エラー",
                f"PDF出力中にエラーが発生しました:\n{str(e)}"
            )
