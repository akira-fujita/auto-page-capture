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
