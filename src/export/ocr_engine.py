# src/export/ocr_engine.py
"""OCRエンジン: 画像から文字とその位置を認識する"""

from dataclasses import dataclass


@dataclass
class TextBox:
    """認識された1テキスト片。座標は正規化(0..1)・左下原点。"""

    text: str
    x: float
    y: float
    w: float
    h: float
    confidence: float
