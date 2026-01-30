# src/ui/region_selector.py
"""画面上で領域を選択するオーバーレイウィジェット"""

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QCursor


class RegionSelector(QWidget):
    """画面全体を覆う半透明オーバーレイで領域選択"""

    region_selected = pyqtSignal(QRect)  # 選択完了時に発火
    selection_cancelled = pyqtSignal()   # キャンセル時に発火

    def __init__(self):
        super().__init__()
        self.start_pos: QPoint | None = None
        self.current_pos: QPoint | None = None
        self.selection: QRect | None = None

        self._init_ui()

    def _init_ui(self):
        """UIを初期化"""
        # フレームレスで全画面
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

        # 全画面サイズを取得（マルチモニター対応）
        screen = QApplication.primaryScreen()
        geometry = screen.geometry()

        # 全てのスクリーンを含む領域を計算
        all_screens = QApplication.screens()
        min_x = min(s.geometry().x() for s in all_screens)
        min_y = min(s.geometry().y() for s in all_screens)
        max_x = max(s.geometry().x() + s.geometry().width() for s in all_screens)
        max_y = max(s.geometry().y() + s.geometry().height() for s in all_screens)

        self.setGeometry(min_x, min_y, max_x - min_x, max_y - min_y)
        self.screen_offset = QPoint(min_x, min_y)

    def paintEvent(self, event):
        """描画イベント"""
        painter = QPainter(self)

        # 半透明の暗いオーバーレイ
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        # 選択領域があれば描画
        if self.start_pos and self.current_pos:
            rect = QRect(self.start_pos, self.current_pos).normalized()

            # 選択領域を透明にする（穴を開ける）
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)

            # 選択領域の枠線を描画
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(QColor(0, 122, 255), 2)
            painter.setPen(pen)
            painter.drawRect(rect)

            # サイズを表示
            size_text = f"{rect.width()} x {rect.height()}"
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(rect.x() + 5, rect.y() - 5, size_text)

        # 説明テキスト
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(20, 30, "ドラッグで領域を選択 / Escでキャンセル")

    def mousePressEvent(self, event):
        """マウス押下"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.pos()
            self.current_pos = event.pos()
            self.update()

    def mouseMoveEvent(self, event):
        """マウス移動"""
        if self.start_pos:
            self.current_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        """マウスリリース"""
        if event.button() == Qt.MouseButton.LeftButton and self.start_pos:
            self.current_pos = event.pos()
            rect = QRect(self.start_pos, self.current_pos).normalized()

            # 最小サイズチェック
            if rect.width() > 10 and rect.height() > 10:
                # スクリーン座標に変換
                screen_rect = QRect(
                    rect.x() + self.screen_offset.x(),
                    rect.y() + self.screen_offset.y(),
                    rect.width(),
                    rect.height()
                )
                self.selection = screen_rect
                self.region_selected.emit(screen_rect)

            self.close()

    def keyPressEvent(self, event):
        """キー押下"""
        if event.key() == Qt.Key.Key_Escape:
            self.selection_cancelled.emit()
            self.close()
