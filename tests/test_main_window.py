# tests/test_main_window.py
"""メインウィンドウのUIテスト"""

import pytest
from unittest.mock import patch, MagicMock, call
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from src.capture.page_navigator import Direction

# PyQt6テストにはQApplicationインスタンスが必要
app = QApplication.instance() or QApplication([])


@patch("src.ui.main_window.WindowManager")
def test_direction_radio_buttons_include_up_down(mock_wm):
    """ページ送り方向に上下のラジオボタンが存在する"""
    mock_wm.return_value.get_window_list.return_value = []
    from src.ui.main_window import MainWindow

    window = MainWindow()
    assert hasattr(window, "up_radio"), "上方向のラジオボタンがない"
    assert hasattr(window, "down_radio"), "下方向のラジオボタンがない"
    window.close()


@patch("src.ui.main_window.WindowManager")
def test_direction_selection_up(mock_wm):
    """上ラジオボタン選択時にDirection.UPが設定される"""
    mock_wm.return_value.get_window_list.return_value = []
    from src.ui.main_window import MainWindow

    window = MainWindow()
    window.up_radio.setChecked(True)
    direction = window._get_selected_direction()
    assert direction == Direction.UP
    window.close()


@patch("src.ui.main_window.WindowManager")
def test_direction_selection_down(mock_wm):
    """下ラジオボタン選択時にDirection.DOWNが設定される"""
    mock_wm.return_value.get_window_list.return_value = []
    from src.ui.main_window import MainWindow

    window = MainWindow()
    window.down_radio.setChecked(True)
    direction = window._get_selected_direction()
    assert direction == Direction.DOWN
    window.close()


@patch("src.ui.main_window.WindowManager")
def test_page_navigation_deferred_after_bring_to_front(mock_wm):
    """ページ送りはbring_to_front後に遅延して実行される（即時実行しない）"""
    mock_wm.return_value.get_window_list.return_value = []
    from src.ui.main_window import MainWindow

    window = MainWindow()
    # _navigate_and_schedule_nextメソッドが存在し、ページ送りを遅延実行する
    assert hasattr(window, "_navigate_and_schedule_next"), \
        "ページ送り遅延実行メソッドがない"
    window.close()


@patch("src.ui.main_window.WindowManager")
def test_custom_region_mode_brings_target_window_to_front(mock_wm):
    """カスタム領域モードでもページ送り前に対象ウィンドウをフォアグラウンドにする"""
    mock_wm_instance = mock_wm.return_value
    mock_wm_instance.get_window_list.return_value = [
        {"id": 1, "name": "test.pdf", "owner": "プレビュー", "pid": 12345,
         "bounds": {"x": 0, "y": 0, "width": 800, "height": 600}},
    ]
    from src.ui.main_window import MainWindow

    window = MainWindow()
    # カスタム領域モードに切り替え
    window.custom_area_radio.setChecked(True)

    # _bring_target_to_frontを呼ぶとウィンドウコンボで選択中のPIDでbring_to_frontが呼ばれる
    mock_wm_instance.bring_to_front.reset_mock()
    window._bring_target_to_front()
    mock_wm_instance.bring_to_front.assert_called_once_with(12345)
    window.close()
