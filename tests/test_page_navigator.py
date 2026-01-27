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
