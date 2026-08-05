"""既存PDFの目次を解析して章範囲を提案するダイアログ"""

import tempfile
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QCheckBox,
    QPushButton, QGroupBox, QTableWidget, QTableWidgetItem,
    QMessageBox, QApplication, QProgressDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from src.export.toc_analyzer import (
    ClaudeTocEngine, ChapterRange, TocEntry, compute_offset, entries_to_chapters, is_chapter,
)
from src.export.pdf_splitter import PdfSplitter


_TOC_HELP_TEXT = (
    "目次ページを読み取って、章の開始ページを自動入力する機能です。\n\n"
    "手順:\n"
    "1. ① 目次のPDFページ範囲 — 目次が載っているPDFのページを指定（両端を含む）。\n"
    "2. ② ページ番号アンカー — 目次で「1ページ」と書かれた本文が、PDFでは何ページ目か"
    "を指定。印刷ページとPDFページのズレを1点で補正します。\n"
    "3. 必要なら「最初の章より前を前付けとして残す」をチェック。\n"
    "4.「解析する」を押すと、章名とページ範囲の候補が表に出ます"
    "（前付けのローマ数字ページは自動で別扱い）。\n"
    "5. 出力したい章だけチェック。「章のみ」で部見出し・参考文献・索引を一括で外せます。\n"
    "6.「この内容で章を設定」で分割画面に反映します。"
)


class _CoverDetectCancelled(Exception):
    """章扉検出のキャンセル"""


class _CoverDetectWorker(QThread):
    """章扉検出をUIスレッドの外で実行する

    claude CLI の呼び出しは1回あたり数十秒かかるため、メインスレッドで走らせると
    ダイアログが応答不能になる。進捗はシグナルで通知し、キャンセルも受け付ける。
    """

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(list)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, detect_fn, parent=None):
        super().__init__(parent)
        self._detect_fn = detect_fn
        self._cancelled = False

    def cancel(self):
        """キャンセルを要求する（進行中のCLI呼び出しの完了後に停止する）"""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self):
        from src.export.page_sheet import SheetCancelled  # noqa: F401  (except節で使う)

        self.progress.emit("ページ画像の準備を開始しました…")
        try:
            covers = self._detect_fn()
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.finished_ok.emit(covers)
        except (_CoverDetectCancelled, SheetCancelled):
            self.cancelled.emit()
        except Exception as e:
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.failed.emit(str(e))


class PdfTocAnalyzeDialog(QDialog):
    """既存PDFの目次から章を自動解析するダイアログ"""

    def __init__(self, pdf_path: Path, page_count: int, engine=None, splitter=None, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.page_count = page_count
        self.engine = engine or ClaudeTocEngine()
        self.splitter = splitter or PdfSplitter()
        self._entries = []
        self._mode = "toc"
        self._detected_pages: list[tuple[str, int]] = []
        self._source_label_text = ""
        self.result_ranges = []
        self.warnings = []
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("目次から章を自動解析")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        n = self.page_count

        # ヘッダ（使い方ボタン）
        header = QHBoxLayout()
        header.addStretch()
        self.help_btn = QPushButton("❓ 使い方")
        self.help_btn.setToolTip("この画面の使い方（手順）を表示します")
        self.help_btn.clicked.connect(self._show_help)
        header.addWidget(self.help_btn)
        layout.addLayout(header)

        # ① 目次ページ範囲(inclusive)
        toc_group = QGroupBox("① 目次のPDFページ範囲(両端を含む)")
        toc_layout = QHBoxLayout(toc_group)
        self.toc_start_spin = QSpinBox(); self.toc_start_spin.setRange(1, max(1, n)); self.toc_start_spin.setPrefix("p.")
        self.toc_end_spin = QSpinBox(); self.toc_end_spin.setRange(1, max(1, n)); self.toc_end_spin.setPrefix("p.")
        self.toc_end_spin.setValue(min(2, n))
        self.toc_start_spin.setToolTip("目次が載っているPDFの先頭ページ（表紙から数えた実際のページ番号）")
        self.toc_end_spin.setToolTip("目次が載っているPDFの最終ページ（両端を含む）")
        self.toc_count_label = QLabel()
        toc_layout.addWidget(self.toc_start_spin); toc_layout.addWidget(QLabel("〜"))
        toc_layout.addWidget(self.toc_end_spin); toc_layout.addWidget(self.toc_count_label)
        toc_layout.addStretch()
        layout.addWidget(toc_group)

        # ② アンカー
        anchor_group = QGroupBox("② ページ番号アンカー(ズレ補正)")
        anchor_outer = QVBoxLayout(anchor_group)
        anchor_row = QHBoxLayout()
        self.anchor_printed_spin = QSpinBox(); self.anchor_printed_spin.setRange(1, 99999); self.anchor_printed_spin.setPrefix("印刷 p.")
        self.anchor_pdf_spin = QSpinBox(); self.anchor_pdf_spin.setRange(1, max(1, n)); self.anchor_pdf_spin.setPrefix("PDF #")
        self.anchor_printed_spin.setToolTip(
            "本文に『ページ番号』として印刷されている数字（目次に載る番号）。\n"
            "例: 本文が 1 から始まるなら 1。"
        )
        self.anchor_pdf_spin.setToolTip(
            "上の印刷ページが、PDFでは何ページ目にあたるか。\n"
            "印刷ページとPDFページのズレをこの1点で補正します。"
        )
        anchor_row.addWidget(self.anchor_printed_spin); anchor_row.addWidget(QLabel("="))
        anchor_row.addWidget(self.anchor_pdf_spin); anchor_row.addStretch()
        anchor_outer.addLayout(anchor_row)
        self.anchor_example = QLabel(); self.anchor_example.setStyleSheet("color:#666;")
        anchor_outer.addWidget(self.anchor_example)
        layout.addWidget(anchor_group)

        self.preface_check = QCheckBox("最初の章より前のページを「前付け」として別章に残す")
        self.preface_check.setToolTip(
            "最初の章より前（表紙・まえがき等）を『前付け』として1章にまとめて残します。"
        )
        layout.addWidget(self.preface_check)

        self.analyze_btn = QPushButton("解析する")
        self.analyze_btn.setToolTip(
            "指定した目次ページを画像化し、claude CLI で章名とページ番号を読み取ります。"
        )
        self.analyze_btn.clicked.connect(self._run_analyze)
        layout.addWidget(self.analyze_btn)

        # claude を使わない検出（しおり・本文テキスト）。無料なのでまずこれを試せる
        self.text_btn = QPushButton("テキストから検出（claude を使わない・無料）")
        self.text_btn.setToolTip(
            "PDFのしおり（ブックマーク）や本文の章見出しテキストから章を検出します。\n"
            "claude を呼ばないので利用枠を消費しません。①②の指定は不要です。\n"
            "文字情報を持たないPDF（スキャン・画面キャプチャ）では使えません。"
        )
        self.text_btn.clicked.connect(self._run_text_detect)
        layout.addWidget(self.text_btn)

        # 目次にページ番号が印字されていない本（Kindleの画面キャプチャ等）向け
        self.cover_btn = QPushButton("目次にページ番号が無い本（章扉を全ページから検出）")
        self.cover_btn.setToolTip(
            "目次にページ番号が載っていない本向け。全ページをサムネイル化して"
            "章扉ページそのものを探すため、①②の指定は不要です。\n"
            "ページ画像を claude CLI に送るので、Claude の利用枠を消費します。"
        )
        self.cover_btn.clicked.connect(self._run_cover_detect)
        layout.addWidget(self.cover_btn)

        self.summary_label = QLabel(); layout.addWidget(self.summary_label)

        # 出力対象の選別ボタン
        select_row = QHBoxLayout()
        self.chapter_only_btn = QPushButton("章のみ")
        self.select_all_btn = QPushButton("全選択")
        self.select_none_btn = QPushButton("全解除")
        self.chapter_only_btn.setToolTip(
            "章の行（例: 第1章 / 9章 / 序章・終章 / Chapter 1）だけチェックし、"
            "部見出し・参考文献・索引などを出力対象から外します。"
        )
        self.select_all_btn.setToolTip("すべての行を出力対象にします。")
        self.select_none_btn.setToolTip("すべての行の出力対象を外します。")
        self.chapter_only_btn.clicked.connect(self._on_chapter_only)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        for b in (self.chapter_only_btn, self.select_all_btn, self.select_none_btn):
            select_row.addWidget(b)
        select_row.addStretch()
        layout.addLayout(select_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["出力", "章名", "→ PDFページ範囲"])
        self.table.setToolTip("チェックした章だけが出力対象になります。")
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)
        self.warning_label = QLabel(); self.warning_label.setStyleSheet("color:#d32f2f;"); self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)

        btns = QHBoxLayout(); btns.addStretch()
        cancel = QPushButton("キャンセル"); cancel.clicked.connect(self.reject); btns.addWidget(cancel)
        self.apply_btn = QPushButton("この内容で章を設定(既存の行は置換されます)")
        self.apply_btn.clicked.connect(self.accept); self.apply_btn.setEnabled(False); btns.addWidget(self.apply_btn)
        layout.addLayout(btns)

        # ライブ更新
        self.toc_start_spin.valueChanged.connect(self._update_labels)
        self.toc_start_spin.valueChanged.connect(self._sync_toc_end_min)
        self.toc_end_spin.valueChanged.connect(self._update_labels)
        self.anchor_printed_spin.valueChanged.connect(self._on_anchor_changed)
        self.anchor_pdf_spin.valueChanged.connect(self._on_anchor_changed)
        self.preface_check.toggled.connect(self._on_preface_toggled)
        self._sync_toc_end_min(self.toc_start_spin.value())
        self._update_labels()

    def _show_help(self):
        QMessageBox.information(self, "使い方 — 目次から章を自動解析", _TOC_HELP_TEXT)

    def _sync_toc_end_min(self, start_value: int):
        self.toc_end_spin.setMinimum(start_value)

    def _update_labels(self):
        start, end = self.toc_start_spin.value(), self.toc_end_spin.value()
        count = max(0, end - start + 1)
        self.toc_count_label.setText(f"（{count}ページを解析）")
        offset = compute_offset(self.anchor_pdf_spin.value(), self.anchor_printed_spin.value())
        self.anchor_example.setText(
            f"例: 印刷 p.{self.anchor_printed_spin.value()} は PDF の {self.anchor_pdf_spin.value()} ページ目 "
            f"(ズレ offset={offset:+d})"
        )

    def _on_anchor_changed(self, _v):
        self._update_labels()
        if self._entries:
            self._recompute(reset_selection=False)

    def _on_preface_toggled(self, _checked: bool):
        if self._mode in ("cover", "text") and self._detected_pages:
            # 物理ページ直取りの結果は保持した検出ページから組み直す
            self._apply_detected_pages(
                self._detected_pages, self._mode, self._source_label_text
            )
            return
        if self._entries:
            self._recompute(reset_selection=False)

    def _selected_page_indices(self) -> list[int]:
        start = self.toc_start_spin.value()
        end = max(self.toc_end_spin.value(), start)
        return [p - 1 for p in range(start, end + 1)]  # 0始まりindex, inclusive

    def _run_analyze(self):
        indices = self._selected_page_indices()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                paths = []
                for idx in indices:
                    out = Path(tmp) / f"toc_{idx}.png"
                    self.splitter.render_page_image(self.pdf_path, idx, out)
                    paths.append(out)
                self._entries = self.engine.analyze(paths)
                self._mode = "toc"
        except FileNotFoundError:
            self._reset_state()
            QMessageBox.critical(self, "エラー", "claude CLI が見つかりませんでした。手動でページを入力してください。")
            return
        except Exception as e:
            self._reset_state()
            QMessageBox.critical(self, "エラー", f"目次の解析に失敗しました:\n{e}\n\n手動でページを入力してください。")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._recompute()

    # --- テキストから検出（claude を使わない） -------------------------------

    _TEXT_SOURCE_LABELS = {
        "bookmark": "しおり",
        "heading": "本文見出し",
    }

    def _run_text_detect(self):
        """しおり・本文テキストから章を検出して表に出す"""
        try:
            result = self.splitter.detect_chapters_auto(self.pdf_path)
        except Exception as e:
            QMessageBox.critical(
                self, "エラー",
                f"テキストからの検出に失敗しました:\n{e}\n\n手動でページを入力してください。",
            )
            return

        if not result.has_text_layer:
            QMessageBox.information(
                self, "テキストがありません",
                "このPDFは文字情報を含まないため、テキストからは検出できません。\n"
                "（スキャンや画面キャプチャのPDFの可能性があります）\n"
                "「章扉を全ページから検出」をお試しください。",
            )
            return

        if not result.chapters:
            QMessageBox.information(
                self, "章が見つかりません",
                "しおりからも本文テキストからも章を検出できませんでした。\n"
                "目次解析か章扉検出をお試しください。",
            )
            return

        if result.source == "toc":
            # 目次の印字ページは物理ページではないので、既存のアンカー補正を通す
            self._entries = [
                TocEntry(name=name, printed_page=page) for name, page in result.chapters
            ]
            self._mode = "toc"
            self._recompute()
            QMessageBox.information(
                self, "目次の印字ページを使いました",
                "本文の章見出しが見つからなかったため、目次に印字されたページ番号を"
                "使いました。\n"
                "②のアンカー（印刷ページ = PDFページ）が正しいか確認してください。",
            )
            return

        chapters = self._validate_covers(result.chapters)
        if not chapters:
            QMessageBox.information(
                self, "章が見つかりません",
                "検出したページがPDFの範囲外でした。手動でページを入力してください。",
            )
            return

        self._apply_detected_pages(
            chapters, mode="text",
            source_label=self._TEXT_SOURCE_LABELS.get(result.source, "テキスト"),
        )

    # --- 章扉から検出（目次にページ番号が無い本向け） -----------------------

    def _detect_chapter_covers(self) -> list[tuple[str, int]]:
        """全ページのサムネイルから章扉ページを検出する（2パス）

        1パス目: コンタクトシートから章扉ページを見つける
        2パス目: そのページだけ拡大し、本当に章扉かの検証と章名の書き写しをする
        """
        from src.export import chapter_cover_detector as detector
        from src.export.page_sheet import build_contact_sheet, SheetCancelled

        with tempfile.TemporaryDirectory(prefix="chapter_covers_") as tmpdir:
            def notify(message: str):
                callback = getattr(self, "_progress_callback", None)
                if callback:
                    callback(message)

            def raise_if_cancelled():
                check = getattr(self, "_cancel_check", None)
                if check and check():
                    raise _CoverDetectCancelled()

            def cancel_check() -> bool:
                check = getattr(self, "_cancel_check", None)
                return bool(check and check())

            def sheet_builder(pages: list[int], out_path: str) -> str:
                raise_if_cancelled()
                notify(f"ページ画像を作成中… (p.{pages[0]}-{pages[-1]})")
                return build_contact_sheet(
                    self.pdf_path, pages, Path(out_path), is_cancelled=cancel_check
                )

            def title_sheet_builder(pages: list[int], out_path: str) -> str:
                raise_if_cancelled()
                notify("章名を読み取り中…")
                # 章名を読み取るため拡大して並べる
                return build_contact_sheet(
                    self.pdf_path, pages, Path(out_path),
                    columns=2, thumb_width=600, thumb_height=800,
                    is_cancelled=cancel_check,
                )

            def runner(prompt: str, image_path: str) -> str:
                raise_if_cancelled()
                notify("claude が画像を読み取っています…")
                check = getattr(self, "_cancel_check", None)
                return detector.run_claude_cli(
                    prompt, image_path, is_cancelled=check
                )

            covers = detector.detect_chapters_from_images(
                page_count=self.page_count,
                output_dir=tmpdir,
                runner=runner,
                sheet_builder=sheet_builder,
            )
            if not covers:
                return []
            return detector.refine_chapter_names(
                covers,
                output_dir=tmpdir,
                runner=runner,
                sheet_builder=title_sheet_builder,
            )

    def _run_cover_detect(self):
        """章扉検出を実行し、結果を章範囲として表に出す"""
        # ページ画像が外部（Claude）に渡り、利用枠も消費するので必ず確認する
        answer = QMessageBox.question(
            self, "章扉から検出",
            f"全 {self.page_count} ページをサムネイル化して claude CLI に送り、"
            "章扉ページを探します。\n"
            "Claude の利用枠を消費し、数分かかることがあります。実行しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._cover_aborted = False
        covers = self._detect_covers_with_progress()
        if self._cover_aborted:
            # キャンセル・失敗は検出側で伝えているので何も出さない
            return
        covers = self._validate_covers(covers)
        if not covers:
            QMessageBox.information(
                self, "章扉が見つかりません",
                "ページ画像から章扉を検出できませんでした。\n"
                "手動でページを入力してください。",
            )
            return

        self._apply_detected_pages(covers, mode="cover", source_label="章扉")

    def _detect_covers_with_progress(self) -> list[tuple[str, int]]:
        """ワーカースレッドで検出し、進捗ダイアログで待つ"""
        worker = _CoverDetectWorker(self._detect_chapter_covers, self)
        self._progress_callback = worker.progress.emit
        self._cancel_check = worker.is_cancelled

        progress = QProgressDialog(
            "ページ画像から章扉を検出しています…", "キャンセル", 0, 0, self
        )
        progress.setWindowTitle("章扉から検出")
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)

        outcome: dict = {}

        def on_finished(covers):
            outcome["covers"] = covers
            progress.close()

        def on_failed(message: str):
            outcome["error"] = message
            progress.close()

        def on_cancelled():
            outcome["cancelled"] = True
            progress.close()

        worker.progress.connect(progress.setLabelText)
        worker.finished_ok.connect(on_finished)
        worker.failed.connect(on_failed)
        worker.cancelled.connect(on_cancelled)
        progress.canceled.connect(worker.cancel)

        worker.start()
        progress.exec()

        # キャンセル時も進行中のCLI呼び出しの終了を待ってから片付ける
        if worker.isRunning():
            worker.cancel()
            worker.wait()

        if outcome.get("cancelled") or worker.is_cancelled():
            self._cover_aborted = True
            return []
        if "error" in outcome:
            # ここでエラーを伝えたので、呼び出し側では追加のメッセージを出さない
            self._cover_aborted = True
            QMessageBox.critical(
                self, "エラー",
                f"章扉の検出に失敗しました:\n{outcome['error']}\n\n"
                "手動でページを入力してください。",
            )
            return []
        return outcome.get("covers") or []

    def _apply_detected_pages(
        self, chapters: list[tuple[str, int]], mode: str, source_label: str
    ):
        """物理ページ直取りの検出結果（章扉・テキスト）を章範囲にして表に出す"""
        # 前付けトグルで組み直せるよう、検出結果そのものを保持する
        self._detected_pages = list(chapters)
        ranges = []
        for i, (name, page) in enumerate(chapters):
            start = page - 1  # 0始まり
            end = (chapters[i + 1][1] - 2) if i + 1 < len(chapters) else self.page_count - 1
            ranges.append(ChapterRange(name, start, end))

        if self.preface_check.isChecked() and ranges and ranges[0].start > 0:
            ranges = [ChapterRange("前付け", 0, ranges[0].start - 1)] + ranges

        # 目次解析の再計算（アンカー変更等）でこの結果を壊さないようにする
        self._entries = []
        self._mode = mode
        self._source_label_text = source_label
        self.result_ranges = ranges
        self.warnings = []
        self._refresh_table()

    def _validate_covers(self, covers: list[tuple[str, int]]) -> list[tuple[str, int]]:
        """検出ページを検証する（範囲内・厳密増加・重複なし）"""
        valid: list[tuple[str, int]] = []
        last_page = 0
        for name, page in sorted(covers, key=lambda c: c[1]):
            if not isinstance(page, int) or not 1 <= page <= self.page_count:
                continue
            if page <= last_page:
                continue
            valid.append((name.strip() or f"章扉 p.{page}", page))
            last_page = page
        return valid

    def _reset_state(self):
        self._entries = []
        self._mode = "toc"
        self._detected_pages = []
        self._source_label_text = ""
        self.result_ranges = []
        self.warnings = []
        self._refresh_table()
        self.apply_btn.setEnabled(False)

    def _recompute(self, reset_selection: bool = True):
        offset = compute_offset(self.anchor_pdf_spin.value(), self.anchor_printed_spin.value())
        ranges, warnings = entries_to_chapters(self._entries, offset, self.page_count)
        # 前付けオプション
        if self.preface_check.isChecked() and ranges and ranges[0].start > 0:
            ranges = [ChapterRange("前付け", 0, ranges[0].start - 1)] + ranges
        self.result_ranges = ranges
        self.warnings = warnings
        self._refresh_table(reset_selection=reset_selection)

    @property
    def selected_ranges(self) -> list[ChapterRange]:
        """チェックされている行に対応する ChapterRange をテーブル順で返す。"""
        selected = []
        for i, c in enumerate(self.result_ranges):
            item = self.table.item(i, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                selected.append(c)
        return selected

    def _refresh_table(self, reset_selection: bool = True):
        # 再計算(アンカー/前付け変更)では選択状態を保持する。名前ごとに以前の
        # チェック状態を出現順で控え、同名行も位置で区別する。新規名はチェック済み。
        prior: dict[str, list[bool]] = {}
        if not reset_selection:
            for i in range(self.table.rowCount()):
                name_item = self.table.item(i, 1)
                if name_item is None:
                    continue
                checked = self.table.item(i, 0).checkState() == Qt.CheckState.Checked
                prior.setdefault(name_item.text(), []).append(checked)

        # 行を作り直す間は itemChanged が誤発火しないようブロックする
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.result_ranges))
        consumed: dict[str, int] = {}
        for i, c in enumerate(self.result_ranges):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            if reset_selection:
                keep = True
            else:
                states = prior.get(c.name)
                idx = consumed.get(c.name, 0)
                # 既知の名前は出現順で対応、未知/超過分はチェック済み(新規扱い)
                keep = states[idx] if states is not None and idx < len(states) else True
                consumed[c.name] = idx + 1
            check.setCheckState(Qt.CheckState.Checked if keep else Qt.CheckState.Unchecked)
            self.table.setItem(i, 0, check)
            self.table.setItem(i, 1, QTableWidgetItem(c.name))
            self.table.setItem(i, 2, QTableWidgetItem(f"p.{c.start + 1}-{c.end + 1}"))
        self.table.blockSignals(False)
        self.warning_label.setText("\n".join(self.warnings))
        self._update_selection_ui()

    def _update_selection_ui(self):
        """サマリ表示と Apply ボタン活性を選択状態に追従させる。"""
        selected = len(self.selected_ranges)
        if self._mode in ("cover", "text"):
            label = self._source_label_text or "章扉"
            # 前付けは検出結果ではないので件数に含めない
            source, detected = f"{label}から", len(self._detected_pages)
        else:
            source, detected = "目次から", len(self._entries)
        self.summary_label.setText(
            f"{source} {detected} 件検出 → {selected} 章を出力対象。"
            "確定すると既存の章一覧は置き換えられます。"
        )
        self.apply_btn.setEnabled(selected > 0)

    def _on_item_changed(self, _item):
        self._update_selection_ui()

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            self.table.item(i, 0).setCheckState(state)
        self.table.blockSignals(False)
        self._update_selection_ui()

    def _on_chapter_only(self):
        """「章」と判定できる行だけをチェックする。0件一致なら警告して状態維持。"""
        matches = [i for i, c in enumerate(self.result_ranges) if is_chapter(c.name)]
        if not matches:
            QMessageBox.information(
                self, "章が見つかりません",
                "章として判定できる見出しがありませんでした。手動で選択してください。",
            )
            return
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            state = Qt.CheckState.Checked if i in matches else Qt.CheckState.Unchecked
            self.table.item(i, 0).setCheckState(state)
        self.table.blockSignals(False)
        self._update_selection_ui()
