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
