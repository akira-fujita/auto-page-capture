# tests/test_chapter_dialog.py
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image
from PyQt6.QtWidgets import QApplication

from src.ui.chapter_dialog import ChapterDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def image_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = []
        for i in range(2):
            p = Path(tmpdir) / f"page_{i}.png"
            Image.new("RGB", (50, 50), "white").save(p, "PNG")
            paths.append(p)
        yield paths


def test_ocr_checkbox_default_on_and_forwarded(qapp, image_paths, monkeypatch):
    with tempfile.TemporaryDirectory() as outdir:
        dialog = ChapterDialog(image_paths, Path(outdir), keep_images=True)
        assert dialog.ocr_check.isChecked() is True

        calls = []
        monkeypatch.setattr(
            dialog.pdf_generator,
            "generate",
            lambda paths, out, ocr=False, ocr_engine=None: calls.append(ocr),
        )
        dialog.merge_check.setChecked(True)
        dialog.chapter_pdf_check.setChecked(False)
        # 通知/メッセージボックスを抑止
        monkeypatch.setattr("src.ui.chapter_dialog.QMessageBox.information", lambda *a, **k: None)
        monkeypatch.setattr("src.utils.notification.send_notification", lambda *a, **k: None)
        # Finderを実際に開かない / ダイアログを閉じない (ヘッドレス化)
        popen_calls = []
        monkeypatch.setattr(
            "src.ui.chapter_dialog.subprocess.Popen",
            lambda *a, **k: popen_calls.append((a, k)),
        )
        monkeypatch.setattr(dialog, "accept", lambda: None)

        dialog._export_pdfs()
        assert calls == [True]
        # Popenはスタブ済み(実際にFinderを開いていない)で、open呼び出しが
        # スタブを経由していることを確認
        assert len(popen_calls) == 1
        (popen_args, _popen_kwargs) = popen_calls[0]
        assert popen_args[0][0] == "open"
