# src/export/ocr_engine.py
"""OCRエンジン: 画像から文字とその位置を認識する"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TextBox:
    """認識された1テキスト片。座標は正規化(0..1)・左下原点。"""

    text: str
    x: float
    y: float
    w: float
    h: float
    confidence: float


class VisionOcrEngine:
    """macOS Vision を用いたOCRエンジン"""

    def recognize(self, image_path: Path) -> list["TextBox"]:
        import Vision
        from Foundation import NSURL

        url = NSURL.fileURLWithPath_(str(image_path))
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(["ja-JP", "en-US"])
        request.setUsesLanguageCorrection_(True)

        success, error = handler.performRequests_error_([request], None)
        if not success:
            raise RuntimeError(f"Vision OCR failed: {error}")

        boxes: list[TextBox] = []
        for observation in (request.results() or []):
            candidates = observation.topCandidates_(1)
            if candidates is None or len(candidates) == 0:
                continue
            top = candidates[0]
            bbox = observation.boundingBox()
            boxes.append(
                TextBox(
                    text=top.string(),
                    x=float(bbox.origin.x),
                    y=float(bbox.origin.y),
                    w=float(bbox.size.width),
                    h=float(bbox.size.height),
                    confidence=float(top.confidence()),
                )
            )
        return boxes
