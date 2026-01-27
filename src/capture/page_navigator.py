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
