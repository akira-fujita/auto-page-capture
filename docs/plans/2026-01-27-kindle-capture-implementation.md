# Kindle Page Capture 実装プラン

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** KindleアプリのページをMac上で自動キャプチャし、章ごとに分割可能なPDFとして出力するGUIアプリを構築する

**Architecture:** PyQt6でGUIを構成し、Quartz/AppKitでmacOSのウィンドウ操作、pyautoguiでスクリーンショットとキー操作、img2pdfでPDF生成を行う。メイン画面でキャプチャ設定→自動キャプチャ実行→章分割画面でPDF出力というフローで動作する。

**Tech Stack:** Python 3.x, PyQt6, pyautogui, Pillow, img2pdf, pyobjc (Quartz/AppKit)

---

## Task 1: プロジェクト構造とセットアップ

**Files:**
- Create: `requirements.txt`
- Create: `main.py`
- Create: `src/__init__.py`
- Create: `src/ui/__init__.py`
- Create: `src/capture/__init__.py`
- Create: `src/export/__init__.py`

**Step 1: requirements.txtを作成**

```txt
PyQt6>=6.6.0
pyautogui>=0.9.54
Pillow>=10.0.0
img2pdf>=0.5.1
pyobjc-framework-Quartz>=10.0
pyobjc-framework-Cocoa>=10.0
```

**Step 2: ディレクトリ構造を作成**

```bash
mkdir -p src/ui src/capture src/export resources tests
touch src/__init__.py src/ui/__init__.py src/capture/__init__.py src/export/__init__.py
```

**Step 3: main.pyを作成**

```python
#!/usr/bin/env python3
"""Kindle Page Capture - メインエントリーポイント"""

import sys
from PyQt6.QtWidgets import QApplication
from src.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Kindle Page Capture")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

**Step 4: 仮想環境を作成して依存関係をインストール**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Step 5: コミット**

```bash
git add requirements.txt main.py src/
git commit -m "feat: initialize project structure and dependencies"
```

---

## Task 2: WindowManager - ウィンドウ一覧取得

**Files:**
- Create: `src/capture/window_manager.py`
- Create: `tests/test_window_manager.py`

**Step 1: テストを作成**

```python
# tests/test_window_manager.py
import pytest
from src.capture.window_manager import WindowManager


def test_get_window_list_returns_list():
    """ウィンドウ一覧がリストで返される"""
    wm = WindowManager()
    windows = wm.get_window_list()
    assert isinstance(windows, list)


def test_window_has_required_keys():
    """各ウィンドウに必須キーが含まれる"""
    wm = WindowManager()
    windows = wm.get_window_list()
    if windows:  # ウィンドウがある場合のみテスト
        window = windows[0]
        assert "id" in window
        assert "name" in window
        assert "owner" in window
        assert "bounds" in window


def test_get_content_bounds_excludes_titlebar():
    """コンテンツ領域がタイトルバーを除外している"""
    wm = WindowManager()
    # テスト用の仮bounds
    bounds = {"x": 100, "y": 100, "width": 800, "height": 600}
    content = wm.get_content_bounds(bounds)
    # タイトルバー(28px)を除外
    assert content["y"] == 128
    assert content["height"] == 572
```

**Step 2: テストを実行して失敗を確認**

```bash
pytest tests/test_window_manager.py -v
```

Expected: FAIL (ModuleNotFoundError)

**Step 3: WindowManagerを実装**

```python
# src/capture/window_manager.py
"""macOSのウィンドウ一覧取得と管理"""

from typing import TypedDict
import Quartz
from AppKit import NSWorkspace, NSRunningApplication


class WindowBounds(TypedDict):
    x: int
    y: int
    width: int
    height: int


class WindowInfo(TypedDict):
    id: int
    name: str
    owner: str
    pid: int
    bounds: WindowBounds


class WindowManager:
    """macOSのウィンドウを管理するクラス"""

    TITLEBAR_HEIGHT = 28  # macOSの標準タイトルバー高さ

    def get_window_list(self) -> list[WindowInfo]:
        """表示中のウィンドウ一覧を取得"""
        windows = []
        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID
        )

        for window in window_list:
            # 通常のウィンドウのみ（メニューバーやドックを除外）
            layer = window.get(Quartz.kCGWindowLayer, 0)
            if layer != 0:
                continue

            name = window.get(Quartz.kCGWindowName, "")
            owner = window.get(Quartz.kCGWindowOwnerName, "")

            # 名前がないウィンドウはスキップ
            if not name and not owner:
                continue

            bounds = window.get(Quartz.kCGWindowBounds, {})
            windows.append(WindowInfo(
                id=window.get(Quartz.kCGWindowNumber, 0),
                name=name or "(無題)",
                owner=owner,
                pid=window.get(Quartz.kCGWindowOwnerPID, 0),
                bounds=WindowBounds(
                    x=int(bounds.get("X", 0)),
                    y=int(bounds.get("Y", 0)),
                    width=int(bounds.get("Width", 0)),
                    height=int(bounds.get("Height", 0)),
                ),
            ))

        return windows

    def get_content_bounds(self, bounds: WindowBounds) -> WindowBounds:
        """タイトルバーを除いたコンテンツ領域を計算"""
        return WindowBounds(
            x=bounds["x"],
            y=bounds["y"] + self.TITLEBAR_HEIGHT,
            width=bounds["width"],
            height=bounds["height"] - self.TITLEBAR_HEIGHT,
        )

    def bring_to_front(self, pid: int) -> bool:
        """指定PIDのアプリをフォアグラウンドに移動"""
        apps = NSWorkspace.sharedWorkspace().runningApplications()
        for app in apps:
            if app.processIdentifier() == pid:
                return app.activateWithOptions_(
                    NSRunningApplication.NSApplicationActivateIgnoringOtherApps
                )
        return False
```

**Step 4: テストを実行して成功を確認**

```bash
pytest tests/test_window_manager.py -v
```

Expected: PASS

**Step 5: コミット**

```bash
git add src/capture/window_manager.py tests/test_window_manager.py
git commit -m "feat: add WindowManager for macOS window list retrieval"
```

---

## Task 3: Screenshot - スクリーンショット撮影

**Files:**
- Create: `src/capture/screenshot.py`
- Create: `tests/test_screenshot.py`

**Step 1: テストを作成**

```python
# tests/test_screenshot.py
import pytest
import tempfile
import os
from pathlib import Path
from PIL import Image
from src.capture.screenshot import Screenshot


def test_capture_region_returns_image():
    """指定領域のスクリーンショットがPIL Imageで返される"""
    ss = Screenshot()
    # 小さい領域でテスト
    image = ss.capture_region(0, 0, 100, 100)
    assert isinstance(image, Image.Image)
    assert image.size == (100, 100)


def test_save_image_creates_file():
    """画像がファイルとして保存される"""
    ss = Screenshot()
    image = ss.capture_region(0, 0, 100, 100)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.png"
        ss.save_image(image, path)
        assert path.exists()
        # 保存した画像が読み込める
        saved = Image.open(path)
        assert saved.size == (100, 100)
```

**Step 2: テストを実行して失敗を確認**

```bash
pytest tests/test_screenshot.py -v
```

Expected: FAIL (ModuleNotFoundError)

**Step 3: Screenshotを実装**

```python
# src/capture/screenshot.py
"""スクリーンショット撮影機能"""

from pathlib import Path
from PIL import Image
import pyautogui


class Screenshot:
    """スクリーンショットの撮影と保存を行うクラス"""

    def capture_region(self, x: int, y: int, width: int, height: int) -> Image.Image:
        """指定領域のスクリーンショットを撮影"""
        return pyautogui.screenshot(region=(x, y, width, height))

    def save_image(self, image: Image.Image, path: Path) -> None:
        """画像をファイルに保存"""
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, "PNG")
```

**Step 4: テストを実行して成功を確認**

```bash
pytest tests/test_screenshot.py -v
```

Expected: PASS

**Step 5: コミット**

```bash
git add src/capture/screenshot.py tests/test_screenshot.py
git commit -m "feat: add Screenshot for capturing screen regions"
```

---

## Task 4: PageNavigator - ページ送り

**Files:**
- Create: `src/capture/page_navigator.py`
- Create: `tests/test_page_navigator.py`

**Step 1: テストを作成**

```python
# tests/test_page_navigator.py
import pytest
from unittest.mock import patch, MagicMock
from src.capture.page_navigator import PageNavigator, Direction


def test_direction_enum():
    """方向の列挙型が正しく定義されている"""
    assert Direction.RIGHT.value == "right"
    assert Direction.LEFT.value == "left"


@patch("src.capture.page_navigator.pyautogui")
def test_next_page_sends_correct_key(mock_pyautogui):
    """next_pageが正しい方向キーを送信する"""
    nav = PageNavigator(direction=Direction.RIGHT)
    nav.next_page()
    mock_pyautogui.press.assert_called_once_with("right")


@patch("src.capture.page_navigator.pyautogui")
def test_next_page_left_direction(mock_pyautogui):
    """左方向でnext_pageが左キーを送信する"""
    nav = PageNavigator(direction=Direction.LEFT)
    nav.next_page()
    mock_pyautogui.press.assert_called_once_with("left")
```

**Step 2: テストを実行して失敗を確認**

```bash
pytest tests/test_page_navigator.py -v
```

Expected: FAIL (ModuleNotFoundError)

**Step 3: PageNavigatorを実装**

```python
# src/capture/page_navigator.py
"""ページ送り機能"""

from enum import Enum
import pyautogui


class Direction(Enum):
    """ページ送りの方向"""
    RIGHT = "right"
    LEFT = "left"


class PageNavigator:
    """キー送信でページ送りを行うクラス"""

    def __init__(self, direction: Direction = Direction.RIGHT):
        self.direction = direction

    def next_page(self) -> None:
        """次のページへ移動"""
        pyautogui.press(self.direction.value)

    def set_direction(self, direction: Direction) -> None:
        """ページ送り方向を設定"""
        self.direction = direction
```

**Step 4: テストを実行して成功を確認**

```bash
pytest tests/test_page_navigator.py -v
```

Expected: PASS

**Step 5: コミット**

```bash
git add src/capture/page_navigator.py tests/test_page_navigator.py
git commit -m "feat: add PageNavigator for keyboard page navigation"
```

---

## Task 5: PdfGenerator - PDF生成

**Files:**
- Create: `src/export/pdf_generator.py`
- Create: `tests/test_pdf_generator.py`

**Step 1: テストを作成**

```python
# tests/test_pdf_generator.py
import pytest
import tempfile
from pathlib import Path
from PIL import Image
from src.export.pdf_generator import PdfGenerator


@pytest.fixture
def sample_images():
    """テスト用のサンプル画像を生成"""
    images = []
    for i in range(3):
        img = Image.new("RGB", (100, 100), color=(i * 50, i * 50, i * 50))
        images.append(img)
    return images


@pytest.fixture
def saved_image_paths(sample_images):
    """サンプル画像をファイルとして保存"""
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = []
        for i, img in enumerate(sample_images):
            path = Path(tmpdir) / f"page_{i:03d}.png"
            img.save(path, "PNG")
            paths.append(path)
        yield paths


def test_generate_pdf_creates_file(saved_image_paths):
    """PDFファイルが生成される"""
    gen = PdfGenerator()
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "output.pdf"
        gen.generate(saved_image_paths, output)
        assert output.exists()
        assert output.stat().st_size > 0


def test_generate_pdf_from_range(saved_image_paths):
    """指定範囲の画像からPDFを生成"""
    gen = PdfGenerator()
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "chapter.pdf"
        # インデックス1-2の画像のみ
        gen.generate(saved_image_paths[1:3], output)
        assert output.exists()
```

**Step 2: テストを実行して失敗を確認**

```bash
pytest tests/test_pdf_generator.py -v
```

Expected: FAIL (ModuleNotFoundError)

**Step 3: PdfGeneratorを実装**

```python
# src/export/pdf_generator.py
"""PDF生成機能"""

from pathlib import Path
import img2pdf


class PdfGenerator:
    """画像からPDFを生成するクラス"""

    def generate(self, image_paths: list[Path], output_path: Path) -> None:
        """画像リストからPDFを生成"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # パスを文字列に変換
        paths_str = [str(p) for p in image_paths]

        with open(output_path, "wb") as f:
            f.write(img2pdf.convert(paths_str))
```

**Step 4: テストを実行して成功を確認**

```bash
pytest tests/test_pdf_generator.py -v
```

Expected: PASS

**Step 5: コミット**

```bash
git add src/export/pdf_generator.py tests/test_pdf_generator.py
git commit -m "feat: add PdfGenerator for image to PDF conversion"
```

---

## Task 6: FileManager - ファイル管理

**Files:**
- Create: `src/export/file_manager.py`
- Create: `tests/test_file_manager.py`

**Step 1: テストを作成**

```python
# tests/test_file_manager.py
import pytest
import tempfile
from pathlib import Path
from datetime import date
from src.export.file_manager import FileManager


def test_create_output_directory():
    """出力ディレクトリが作成される"""
    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager(base_path=Path(tmpdir))
        output_dir = fm.create_output_directory("test_capture")
        assert output_dir.exists()
        assert "test_capture" in output_dir.name


def test_output_directory_includes_date():
    """出力ディレクトリ名に日付が含まれる"""
    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager(base_path=Path(tmpdir))
        output_dir = fm.create_output_directory("capture")
        today = date.today().strftime("%Y-%m-%d")
        assert today in output_dir.name


def test_get_image_path():
    """ページ番号に応じた画像パスを取得"""
    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager(base_path=Path(tmpdir))
        output_dir = fm.create_output_directory("test")
        path = fm.get_image_path(output_dir, 5)
        assert path.name == "page_005.png"


def test_cleanup_images():
    """画像ファイルが削除される"""
    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager(base_path=Path(tmpdir))
        output_dir = fm.create_output_directory("test")
        images_dir = output_dir / "images"
        images_dir.mkdir()

        # ダミー画像を作成
        (images_dir / "page_001.png").touch()
        (images_dir / "page_002.png").touch()

        fm.cleanup_images(output_dir)
        assert not images_dir.exists()
```

**Step 2: テストを実行して失敗を確認**

```bash
pytest tests/test_file_manager.py -v
```

Expected: FAIL (ModuleNotFoundError)

**Step 3: FileManagerを実装**

```python
# src/export/file_manager.py
"""ファイル管理機能"""

from pathlib import Path
from datetime import date
import shutil


class FileManager:
    """出力ファイルの管理を行うクラス"""

    def __init__(self, base_path: Path | None = None):
        self.base_path = base_path or Path.home() / "Desktop" / "captures"

    def create_output_directory(self, name: str) -> Path:
        """日付付きの出力ディレクトリを作成"""
        today = date.today().strftime("%Y-%m-%d")
        dir_name = f"{today}_{name}"
        output_dir = self.base_path / dir_name
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def get_image_path(self, output_dir: Path, page_number: int) -> Path:
        """ページ番号に対応する画像パスを取得"""
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        return images_dir / f"page_{page_number:03d}.png"

    def cleanup_images(self, output_dir: Path) -> None:
        """画像ディレクトリを削除"""
        images_dir = output_dir / "images"
        if images_dir.exists():
            shutil.rmtree(images_dir)

    def get_chapter_pdf_path(self, output_dir: Path, index: int, name: str) -> Path:
        """章別PDFのパスを取得"""
        # ファイル名に使えない文字を置換
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        return output_dir / f"chapter_{index:02d}_{safe_name}.pdf"
```

**Step 4: テストを実行して成功を確認**

```bash
pytest tests/test_file_manager.py -v
```

Expected: PASS

**Step 5: コミット**

```bash
git add src/export/file_manager.py tests/test_file_manager.py
git commit -m "feat: add FileManager for output file management"
```

---

## Task 7: MainWindow - メイン画面UI

**Files:**
- Create: `src/ui/main_window.py`

**Step 1: MainWindowを実装**

```python
# src/ui/main_window.py
"""メイン画面UI"""

from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QSpinBox, QSlider,
    QRadioButton, QButtonGroup, QCheckBox, QLineEdit,
    QFileDialog, QProgressBar, QMessageBox, QGroupBox,
)
from PyQt6.QtCore import Qt, QTimer
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

    def _toggle_capture(self):
        """キャプチャ開始/停止を切り替え"""
        if not self.is_capturing:
            self._start_capture()

    def _start_capture(self):
        """キャプチャを開始"""
        if not self.windows:
            QMessageBox.warning(self, "エラー", "ウィンドウが選択されていません")
            return

        idx = self.window_combo.currentIndex()
        if idx < 0:
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

        # ウィンドウをフォアグラウンドに
        window = self.windows[idx]
        self.window_manager.bring_to_front(window["pid"])

        # 少し待ってからキャプチャ開始
        QTimer.singleShot(500, self._capture_page)

    def _capture_page(self):
        """1ページをキャプチャ"""
        if not self.is_capturing or self.current_page >= self.total_pages:
            self._finish_capture()
            return

        idx = self.window_combo.currentIndex()
        window = self.windows[idx]
        bounds = self.window_manager.get_content_bounds(window["bounds"])

        # スクリーンショット撮影
        image = self.screenshot.capture_region(
            bounds["x"], bounds["y"], bounds["width"], bounds["height"]
        )

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

        if self.captured_images:
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
```

**Step 2: アプリを実行して動作確認**

```bash
source venv/bin/activate
python main.py
```

ウィンドウが表示されることを確認。

**Step 3: コミット**

```bash
git add src/ui/main_window.py
git commit -m "feat: add MainWindow with capture settings UI"
```

---

## Task 8: ChapterDialog - 章分割画面UI

**Files:**
- Create: `src/ui/chapter_dialog.py`

**Step 1: ChapterDialogを実装**

```python
# src/ui/chapter_dialog.py
"""章分割ダイアログUI"""

from pathlib import Path
from dataclasses import dataclass
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QListWidget, QListWidgetItem,
    QCheckBox, QLineEdit, QMessageBox, QFrame,
)
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import Qt, pyqtSignal
from PIL import Image
from src.export.pdf_generator import PdfGenerator
from src.export.file_manager import FileManager


@dataclass
class Chapter:
    """章の情報"""
    name: str
    start: int  # 0-indexed
    end: int    # 0-indexed, inclusive


class ThumbnailWidget(QFrame):
    """サムネイル表示ウィジェット"""
    clicked = pyqtSignal(int)

    def __init__(self, image_path: Path, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.is_chapter_start = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # サムネイル画像
        self.image_label = QLabel()
        pixmap = self._load_thumbnail(image_path)
        self.image_label.setPixmap(pixmap)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_label)

        # ページ番号
        self.number_label = QLabel(str(index + 1))
        self.number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.number_label)

        self.setFrameStyle(QFrame.Shape.Box)
        self._update_style()

    def _load_thumbnail(self, path: Path) -> QPixmap:
        """サムネイル用に画像を縮小して読み込み"""
        img = Image.open(path)
        img.thumbnail((80, 120))

        # PIL ImageをQPixmapに変換
        img = img.convert("RGB")
        data = img.tobytes("raw", "RGB")
        qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
        return QPixmap.fromImage(qimg)

    def set_chapter_start(self, is_start: bool):
        """章の開始ページとしてマーク"""
        self.is_chapter_start = is_start
        self._update_style()

    def _update_style(self):
        """スタイルを更新"""
        if self.is_chapter_start:
            self.setStyleSheet("ThumbnailWidget { border: 3px solid #007AFF; background: #E5F0FF; }")
        else:
            self.setStyleSheet("ThumbnailWidget { border: 1px solid #CCC; }")

    def mousePressEvent(self, event):
        """クリックイベント"""
        self.clicked.emit(self.index)


class ChapterDialog(QDialog):
    """章分割ダイアログ"""

    def __init__(self, image_paths: list[Path], output_dir: Path, keep_images: bool, parent=None):
        super().__init__(parent)
        self.image_paths = image_paths
        self.output_dir = output_dir
        self.keep_images = keep_images
        self.pdf_generator = PdfGenerator()
        self.file_manager = FileManager()
        self.chapters: list[Chapter] = []
        self.thumbnails: list[ThumbnailWidget] = []

        self._init_ui()

    def _init_ui(self):
        """UIを初期化"""
        self.setWindowTitle("章の分割")
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        # 説明
        desc = QLabel("サムネイルをクリックして章の開始ページを指定してください")
        layout.addWidget(desc)

        # サムネイル一覧（横スクロール）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(180)

        thumb_container = QWidget()
        thumb_layout = QHBoxLayout(thumb_container)
        thumb_layout.setSpacing(8)

        for i, path in enumerate(self.image_paths):
            thumb = ThumbnailWidget(path, i)
            thumb.clicked.connect(self._on_thumbnail_clicked)
            self.thumbnails.append(thumb)
            thumb_layout.addWidget(thumb)

        thumb_layout.addStretch()
        scroll.setWidget(thumb_container)
        layout.addWidget(scroll)

        # 章リスト
        list_label = QLabel("章リスト:")
        layout.addWidget(list_label)

        self.chapter_list = QListWidget()
        self.chapter_list.setMaximumHeight(150)
        layout.addWidget(self.chapter_list)

        # 章名編集
        edit_layout = QHBoxLayout()
        edit_layout.addWidget(QLabel("章名:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("章を選択してください")
        self.name_edit.setEnabled(False)
        self.name_edit.textChanged.connect(self._on_name_changed)
        edit_layout.addWidget(self.name_edit)

        delete_btn = QPushButton("削除")
        delete_btn.clicked.connect(self._delete_chapter)
        edit_layout.addWidget(delete_btn)
        layout.addLayout(edit_layout)

        # オプション
        self.merge_check = QCheckBox("全体を1つのPDFにもまとめる")
        self.merge_check.setChecked(True)
        layout.addWidget(self.merge_check)

        # ボタン
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        export_btn = QPushButton("PDF出力")
        export_btn.clicked.connect(self._export_pdfs)
        button_layout.addWidget(export_btn)

        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

        # リスト選択時の処理
        self.chapter_list.currentRowChanged.connect(self._on_chapter_selected)

    def _on_thumbnail_clicked(self, index: int):
        """サムネイルがクリックされた"""
        # 既存の章の開始点かチェック
        for ch in self.chapters:
            if ch.start == index:
                # 既存の章を選択
                row = self.chapters.index(ch)
                self.chapter_list.setCurrentRow(row)
                return

        # 新しい章を追加
        chapter_num = len(self.chapters) + 1
        new_chapter = Chapter(
            name=f"第{chapter_num}章",
            start=index,
            end=len(self.image_paths) - 1
        )

        # 挿入位置を決定（開始ページ順）
        insert_pos = 0
        for i, ch in enumerate(self.chapters):
            if ch.start < index:
                insert_pos = i + 1
            else:
                break

        self.chapters.insert(insert_pos, new_chapter)
        self._recalculate_chapter_ranges()
        self._update_chapter_list()
        self._update_thumbnails()

    def _recalculate_chapter_ranges(self):
        """章の範囲を再計算"""
        # 開始ページでソート
        self.chapters.sort(key=lambda c: c.start)

        # 各章の終了ページを次の章の開始-1に設定
        for i, ch in enumerate(self.chapters):
            if i < len(self.chapters) - 1:
                ch.end = self.chapters[i + 1].start - 1
            else:
                ch.end = len(self.image_paths) - 1

    def _update_chapter_list(self):
        """章リストを更新"""
        self.chapter_list.clear()
        for ch in self.chapters:
            text = f"📖 {ch.name}  (ページ {ch.start + 1}-{ch.end + 1})"
            self.chapter_list.addItem(text)

    def _update_thumbnails(self):
        """サムネイルの章マークを更新"""
        chapter_starts = {ch.start for ch in self.chapters}
        for thumb in self.thumbnails:
            thumb.set_chapter_start(thumb.index in chapter_starts)

    def _on_chapter_selected(self, row: int):
        """章が選択された"""
        if 0 <= row < len(self.chapters):
            self.name_edit.setEnabled(True)
            self.name_edit.setText(self.chapters[row].name)
        else:
            self.name_edit.setEnabled(False)
            self.name_edit.clear()

    def _on_name_changed(self, text: str):
        """章名が変更された"""
        row = self.chapter_list.currentRow()
        if 0 <= row < len(self.chapters):
            self.chapters[row].name = text
            self._update_chapter_list()
            self.chapter_list.setCurrentRow(row)

    def _delete_chapter(self):
        """選択中の章を削除"""
        row = self.chapter_list.currentRow()
        if 0 <= row < len(self.chapters):
            del self.chapters[row]
            self._recalculate_chapter_ranges()
            self._update_chapter_list()
            self._update_thumbnails()

    def _export_pdfs(self):
        """PDFを出力"""
        try:
            # 章別PDF
            for i, ch in enumerate(self.chapters):
                chapter_images = self.image_paths[ch.start:ch.end + 1]
                output_path = self.file_manager.get_chapter_pdf_path(
                    self.output_dir, i + 1, ch.name
                )
                self.pdf_generator.generate(chapter_images, output_path)

            # 全体PDF
            if self.merge_check.isChecked() or not self.chapters:
                output_path = self.output_dir / "output.pdf"
                self.pdf_generator.generate(self.image_paths, output_path)

            # 画像削除
            if not self.keep_images:
                self.file_manager.cleanup_images(self.output_dir)

            QMessageBox.information(
                self,
                "完了",
                f"PDFを出力しました:\n{self.output_dir}"
            )
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "エラー", f"PDF出力に失敗しました:\n{e}")
```

**Step 2: アプリを実行して動作確認**

```bash
python main.py
```

キャプチャ完了後に章分割ダイアログが表示されることを確認。

**Step 3: コミット**

```bash
git add src/ui/chapter_dialog.py
git commit -m "feat: add ChapterDialog for chapter-based PDF splitting"
```

---

## Task 9: 統合テストと最終調整

**Files:**
- Modify: `main.py`
- Create: `tests/test_integration.py`

**Step 1: 統合テストを作成**

```python
# tests/test_integration.py
"""統合テスト"""

import pytest
import tempfile
from pathlib import Path
from PIL import Image
from src.capture.window_manager import WindowManager
from src.capture.screenshot import Screenshot
from src.capture.page_navigator import PageNavigator, Direction
from src.export.pdf_generator import PdfGenerator
from src.export.file_manager import FileManager


def test_full_workflow():
    """キャプチャからPDF生成までの一連の流れ"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # FileManagerでディレクトリ作成
        fm = FileManager(base_path=Path(tmpdir))
        output_dir = fm.create_output_directory("test")

        # 仮の画像を作成（実際のキャプチャの代わり）
        image_paths = []
        for i in range(5):
            img = Image.new("RGB", (200, 300), color=(i * 40, 100, 150))
            path = fm.get_image_path(output_dir, i + 1)
            img.save(path, "PNG")
            image_paths.append(path)

        # PDF生成
        pdf_gen = PdfGenerator()

        # 全体PDF
        output_pdf = output_dir / "output.pdf"
        pdf_gen.generate(image_paths, output_pdf)
        assert output_pdf.exists()

        # 章別PDF
        chapter1_pdf = fm.get_chapter_pdf_path(output_dir, 1, "第1章")
        pdf_gen.generate(image_paths[:2], chapter1_pdf)
        assert chapter1_pdf.exists()

        chapter2_pdf = fm.get_chapter_pdf_path(output_dir, 2, "第2章")
        pdf_gen.generate(image_paths[2:], chapter2_pdf)
        assert chapter2_pdf.exists()


def test_window_manager_integration():
    """WindowManagerが実際のウィンドウ一覧を取得できる"""
    wm = WindowManager()
    windows = wm.get_window_list()
    # macOSで実行すれば少なくとも1つはウィンドウがあるはず
    # CI環境ではスキップ
    if windows:
        assert all("id" in w for w in windows)
        assert all("bounds" in w for w in windows)
```

**Step 2: テストを実行**

```bash
pytest tests/ -v
```

Expected: ALL PASS

**Step 3: コミット**

```bash
git add tests/test_integration.py
git commit -m "test: add integration tests for full workflow"
```

---

## Task 10: README作成と最終コミット

**Files:**
- Create: `README.md`

**Step 1: READMEを作成**

```markdown
# Kindle Page Capture

KindleアプリのページをMac上で自動キャプチャし、PDFとして出力するGUIアプリケーション。

## 機能

- macOSのウィンドウ一覧から対象アプリを選択
- 指定ページ数を自動でキャプチャ
- キャプチャ間隔・ページ送り方向を調整可能
- 章ごとにPDFを分割出力（NotebookLMでの要約に便利）
- 全体を1つのPDFにまとめることも可能

## 必要環境

- macOS
- Python 3.10+

## インストール

```bash
git clone <repository-url>
cd auto-page-capture
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 使い方

```bash
source venv/bin/activate
python main.py
```

1. 対象ウィンドウでKindleを選択
2. ページ数、ページ送り方向、キャプチャ間隔を設定
3. 「キャプチャ開始」をクリック
4. キャプチャ完了後、章分割画面でPDFを出力

## 注意事項

- キャプチャ中は対象ウィンドウを動かさないでください
- macOSのスクリーン録画権限が必要です（システム環境設定 > セキュリティとプライバシー > スクリーン収録）

## ライセンス

MIT
```

**Step 2: コミット**

```bash
git add README.md
git commit -m "docs: add README with installation and usage instructions"
```

**Step 3: 全テストを実行して最終確認**

```bash
pytest tests/ -v
```

Expected: ALL PASS

---

## 完了チェックリスト

- [ ] Task 1: プロジェクト構造とセットアップ
- [ ] Task 2: WindowManager - ウィンドウ一覧取得
- [ ] Task 3: Screenshot - スクリーンショット撮影
- [ ] Task 4: PageNavigator - ページ送り
- [ ] Task 5: PdfGenerator - PDF生成
- [ ] Task 6: FileManager - ファイル管理
- [ ] Task 7: MainWindow - メイン画面UI
- [ ] Task 8: ChapterDialog - 章分割画面UI
- [ ] Task 9: 統合テストと最終調整
- [ ] Task 10: README作成と最終コミット
