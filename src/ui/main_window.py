# src/ui/main_window.py
"""メイン画面UI"""

from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QSpinBox, QSlider,
    QRadioButton, QButtonGroup, QCheckBox, QLineEdit,
    QFileDialog, QProgressBar, QMessageBox, QGroupBox,
)
from PyQt6.QtCore import Qt, QTimer, QRect
from src.capture.window_manager import WindowManager, WindowInfo
from src.capture.screenshot import Screenshot
from src.capture.page_navigator import PageNavigator, Direction
from src.export.file_manager import FileManager


class MainWindow(QMainWindow):
    """メインウィンドウ"""

    def __init__(self):
        super().__init__()
        self.window_manager = WindowManager()
        self.screenshot = Screenshot()
        self.page_navigator = PageNavigator()
        self.file_manager = FileManager()

        self.windows: list[WindowInfo] = []
        self.captured_images: list[Path] = []
        self.is_capturing = False
        self.current_page = 0
        self.total_pages = 0
        self.output_dir: Path | None = None
        self.custom_region: QRect | None = None  # カスタム領域

        self._init_ui()
        self._refresh_windows()

    def _init_ui(self):
        """UIを初期化"""
        self.setWindowTitle("Kindle Page Capture")
        self.setMinimumWidth(450)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # ウィンドウ選択
        window_group = QGroupBox("対象ウィンドウ")
        window_layout = QHBoxLayout(window_group)
        self.window_combo = QComboBox()
        self.window_combo.setMinimumWidth(250)
        refresh_btn = QPushButton("更新")
        refresh_btn.clicked.connect(self._refresh_windows)
        window_layout.addWidget(self.window_combo)
        window_layout.addWidget(refresh_btn)
        layout.addWidget(window_group)

        # キャプチャ領域
        area_group = QGroupBox("キャプチャ領域")
        area_layout = QVBoxLayout(area_group)

        # 領域選択ラジオボタン
        self.area_group = QButtonGroup()
        self.window_area_radio = QRadioButton("ウィンドウ全体（タイトルバー除く）")
        self.custom_area_radio = QRadioButton("カスタム領域")
        self.window_area_radio.setChecked(True)
        self.area_group.addButton(self.window_area_radio)
        self.area_group.addButton(self.custom_area_radio)
        area_layout.addWidget(self.window_area_radio)

        # カスタム領域選択行
        custom_layout = QHBoxLayout()
        custom_layout.addWidget(self.custom_area_radio)
        self.select_region_btn = QPushButton("領域を選択...")
        self.select_region_btn.clicked.connect(self._select_region)
        self.select_region_btn.setEnabled(False)
        custom_layout.addWidget(self.select_region_btn)
        self.region_info_label = QLabel("")
        self.region_info_label.setStyleSheet("color: #666;")
        custom_layout.addWidget(self.region_info_label)
        custom_layout.addStretch()
        area_layout.addLayout(custom_layout)

        # ラジオボタン変更時の処理
        self.custom_area_radio.toggled.connect(self._on_area_mode_changed)

        layout.addWidget(area_group)

        # キャプチャ設定
        settings_group = QGroupBox("キャプチャ設定")
        settings_layout = QVBoxLayout(settings_group)

        # ページ数
        page_layout = QHBoxLayout()
        page_layout.addWidget(QLabel("ページ数:"))
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 9999)
        self.page_spin.setValue(10)
        page_layout.addWidget(self.page_spin)
        page_layout.addWidget(QLabel("ページ"))
        page_layout.addStretch()
        settings_layout.addLayout(page_layout)

        # ページ送り方向
        direction_layout = QHBoxLayout()
        direction_layout.addWidget(QLabel("ページ送り方向:"))
        self.direction_group = QButtonGroup()
        self.right_radio = QRadioButton("→ 右")
        self.left_radio = QRadioButton("← 左")
        self.right_radio.setChecked(True)
        self.direction_group.addButton(self.right_radio)
        self.direction_group.addButton(self.left_radio)
        direction_layout.addWidget(self.right_radio)
        direction_layout.addWidget(self.left_radio)
        direction_layout.addStretch()
        settings_layout.addLayout(direction_layout)

        # キャプチャ間隔
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("キャプチャ間隔:"))
        self.interval_slider = QSlider(Qt.Orientation.Horizontal)
        self.interval_slider.setRange(5, 30)  # 0.5秒〜3.0秒
        self.interval_slider.setValue(10)  # 1.0秒
        self.interval_slider.valueChanged.connect(self._update_interval_label)
        self.interval_label = QLabel("1.0秒")
        interval_layout.addWidget(self.interval_slider)
        interval_layout.addWidget(self.interval_label)
        settings_layout.addLayout(interval_layout)

        layout.addWidget(settings_group)

        # 出力設定
        output_group = QGroupBox("出力設定")
        output_layout = QVBoxLayout(output_group)

        self.keep_images_check = QCheckBox("元の画像ファイルも保存する")
        self.keep_images_check.setChecked(True)
        output_layout.addWidget(self.keep_images_check)

        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("保存先:"))
        self.path_edit = QLineEdit(str(Path.home() / "Desktop" / "captures"))
        browse_btn = QPushButton("参照...")
        browse_btn.clicked.connect(self._browse_directory)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(browse_btn)
        output_layout.addLayout(path_layout)

        layout.addWidget(output_group)

        # ボタン
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("キャプチャ開始")
        self.start_btn.clicked.connect(self._toggle_capture)
        self.cancel_btn = QPushButton("キャンセル")
        self.cancel_btn.clicked.connect(self._cancel_capture)
        self.cancel_btn.setEnabled(False)
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)

        # プログレスバー
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 注意事項
        self.warning_label = QLabel(
            "⚠️ キャプチャ中の注意:\n"
            "• 対象ウィンドウを動かさないでください\n"
            "• 他のウィンドウを前面に出さないでください"
        )
        self.warning_label.setStyleSheet("color: #666; font-size: 11px;")
        self.warning_label.setVisible(False)
        layout.addWidget(self.warning_label)

        layout.addStretch()

    def _refresh_windows(self):
        """ウィンドウ一覧を更新"""
        self.windows = self.window_manager.get_window_list()
        self.window_combo.clear()
        for w in self.windows:
            display = f"{w['owner']} - {w['name']}"
            self.window_combo.addItem(display)

    def _update_interval_label(self, value: int):
        """間隔ラベルを更新"""
        seconds = value / 10
        self.interval_label.setText(f"{seconds:.1f}秒")

    def _browse_directory(self):
        """保存先ディレクトリを選択"""
        path = QFileDialog.getExistingDirectory(self, "保存先を選択")
        if path:
            self.path_edit.setText(path)

    def _on_area_mode_changed(self, checked: bool):
        """領域モードが変更された"""
        self.select_region_btn.setEnabled(checked)
        if not checked:
            self.custom_region = None
            self.region_info_label.setText("")

    def _select_region(self):
        """領域選択オーバーレイを表示"""
        from src.ui.region_selector import RegionSelector

        self.hide()  # メインウィンドウを一時的に隠す
        QTimer.singleShot(200, self._show_region_selector)

    def _show_region_selector(self):
        """領域セレクターを表示"""
        from src.ui.region_selector import RegionSelector

        self.region_selector = RegionSelector()
        self.region_selector.region_selected.connect(self._on_region_selected)
        self.region_selector.selection_cancelled.connect(self._on_region_cancelled)
        self.region_selector.show()

    def _on_region_selected(self, rect: QRect):
        """領域が選択された"""
        self.custom_region = rect
        self.region_info_label.setText(f"{rect.width()} x {rect.height()} px")
        self.show()
        self.activateWindow()

    def _on_region_cancelled(self):
        """領域選択がキャンセルされた"""
        self.show()
        self.activateWindow()

    def _toggle_capture(self):
        """キャプチャ開始/停止を切り替え"""
        if not self.is_capturing:
            self._start_capture()

    def _start_capture(self):
        """キャプチャを開始"""
        # カスタム領域モードで領域未選択の場合
        if self.custom_area_radio.isChecked() and not self.custom_region:
            QMessageBox.warning(self, "エラー", "キャプチャ領域を選択してください")
            return

        # ウィンドウモードでウィンドウ未選択の場合
        if self.window_area_radio.isChecked() and not self.windows:
            QMessageBox.warning(self, "エラー", "ウィンドウが選択されていません")
            return

        idx = self.window_combo.currentIndex()
        if self.window_area_radio.isChecked() and idx < 0:
            return

        self.is_capturing = True
        self.current_page = 0
        self.total_pages = self.page_spin.value()
        self.captured_images = []

        # 方向を設定
        direction = Direction.RIGHT if self.right_radio.isChecked() else Direction.LEFT
        self.page_navigator.set_direction(direction)

        # 出力ディレクトリを作成
        self.file_manager.base_path = Path(self.path_edit.text())
        self.output_dir = self.file_manager.create_output_directory("kindle_capture")

        # UI更新
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setRange(0, self.total_pages)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.warning_label.setVisible(True)

        # ウィンドウモードの場合、ウィンドウをフォアグラウンドに
        if self.window_area_radio.isChecked() and idx >= 0:
            window = self.windows[idx]
            self.window_manager.bring_to_front(window["pid"])

        # 少し待ってからキャプチャ開始
        QTimer.singleShot(500, self._capture_page)

    def _capture_page(self):
        """1ページをキャプチャ"""
        if not self.is_capturing or self.current_page >= self.total_pages:
            self._finish_capture()
            return

        # キャプチャ領域を決定
        if self.custom_area_radio.isChecked() and self.custom_region:
            # カスタム領域を使用
            x = self.custom_region.x()
            y = self.custom_region.y()
            width = self.custom_region.width()
            height = self.custom_region.height()
        else:
            # ウィンドウのコンテンツ領域を使用
            idx = self.window_combo.currentIndex()
            window = self.windows[idx]
            bounds = self.window_manager.get_content_bounds(window["bounds"])
            x = bounds["x"]
            y = bounds["y"]
            width = bounds["width"]
            height = bounds["height"]

        # スクリーンショット撮影
        image = self.screenshot.capture_region(x, y, width, height)

        # 保存
        path = self.file_manager.get_image_path(self.output_dir, self.current_page + 1)
        self.screenshot.save_image(image, path)
        self.captured_images.append(path)

        self.current_page += 1
        self.progress_bar.setValue(self.current_page)

        if self.current_page < self.total_pages:
            # ページ送り
            self.page_navigator.next_page()
            # 次のキャプチャをスケジュール
            interval_ms = self.interval_slider.value() * 100
            QTimer.singleShot(interval_ms, self._capture_page)
        else:
            self._finish_capture()

    def _finish_capture(self):
        """キャプチャ完了処理"""
        self.is_capturing = False
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.warning_label.setVisible(False)
        self.progress_bar.setVisible(False)

        if self.captured_images:
            # デスクトップ通知
            from src.utils.notification import send_notification
            send_notification(
                "Kindle Page Capture",
                f"キャプチャ完了: {len(self.captured_images)}ページ"
            )

            # 章分割ダイアログを表示
            from src.ui.chapter_dialog import ChapterDialog
            dialog = ChapterDialog(
                self.captured_images,
                self.output_dir,
                self.keep_images_check.isChecked(),
                self
            )
            dialog.exec()

    def _cancel_capture(self):
        """キャプチャをキャンセル"""
        reply = QMessageBox.question(
            self,
            "確認",
            "キャプチャを中止しますか？\n撮影済みの画像は保持されます。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.is_capturing = False
            self._finish_capture()
