# 目次解析結果からの章選別（章のみフィルタ）— 設計

## 背景・目的

`PdfTocAnalyzeDialog` は本の目次を `claude` CLI で解析し、章名＋PDFページ範囲
（`ChapterRange` の列 = `result_ranges`）を提案する。これが `PdfSplitDialog` に
渡り、章ごとのPDFに分割される。

ユーザーは分割後、**スライド化する価値のある「章」のPDFだけを NotebookLM に
アップロード**したい。しかし解析結果には「章」以外に、部見出し（第I部…）や
巻末項目（参考文献・訳者あとがき・索引）が混ざる。これらは出力対象から外したい。

本機能では、解析結果の各行を**出力対象として選別**できるようにする。

（NotebookLM への自動アップロードは別サブプロジェクトとし、本 spec のスコープ外。
本 spec は「出力する章PDFをクリーンに選別する」ところまで。）

## スコープ

- 対象: 既存PDF分割フローの `PdfTocAnalyzeDialog` のみ。
- 対象外: キャプチャフローの `TocAnalyzeDialog` / `ChapterDialog`（挙動不変）。

## UI 設計（`PdfTocAnalyzeDialog`）

- 結果テーブルを2列→**3列**に変更: `[☑ 選択 | 章名 | → PDFページ範囲]`。
- 解析直後は**全行チェック済み**。
- テーブル下にボタン3つ: **「章のみ」「全選択」「全解除」**。
  - 「章のみ」: `is_chapter(name)` が真の行だけをチェック、他を外す。
    - 一致0件なら警告「章として判定できる見出しがありませんでした」を出し、
      既存のチェック状態は変更しない。
  - 「全選択」/「全解除」: 全行のチェックを一括切替。
- サマリ表示: 「N 件検出 → M 章を出力対象」のように**選択数**を表示。
- **Apply（この内容で章を設定）ボタンの活性**は `selected_ranges` が非空のときのみ。
  （全解除・0件選択では押せない。）
- チェック状態変更でサマリと Apply 活性をライブ更新。

## 章判定ロジック（`toc_analyzer.py` に純粋関数を新設）

Qt 非依存の純粋関数 `is_chapter(name: str) -> bool` を追加。単体テスト可能。

先頭アンカー（`re.match`）で以下いずれかに一致すれば章とみなす:

- `^第?\s*[0-9０-９]+\s*章`   … 「第1章」「1章」「１章」「9章 おわりに」
- `^第?\s*[一二三四五六七八九十百]+\s*章` … 「第一章」
- `^(序章|終章)`
- `^chapter\s+\d+`（大文字小文字無視） … 「Chapter 1」

部見出し（「第II部」＝ローマ数字＋部）や巻末項目（参考文献/訳者あとがき/索引/
付録 など）はいずれのパターンにも一致しないため、自然に非章となる。

判定は完全ではないため、行ごとチェックボックスで**手動修正**できることを最終
フォールバックとする（ヒューリスティックの誤判定は致命的でない）。

`entries_to_chapters` は**変更しない**（全項目で正確な境界を計算し続ける）。
外した行のページはどの章PDFにも含まれない（間のギャップは許容）。残す章の範囲は
再計算しない。

## データフロー

- `PdfTocAnalyzeDialog`
  - `result_ranges`（全件・テーブル表示用）は従来通り維持。
  - **`selected_ranges` プロパティ**を追加: チェック済み行に対応する
    `ChapterRange` だけを、テーブル順で返す。
- `PdfSplitDialog._on_toc_analyze`
  - `if dialog.exec() and dialog.result_ranges:` の真偽ゲートと
    `_apply_toc_ranges(dialog.result_ranges)` の**両方**を
    `dialog.selected_ranges` に変更。

## テスト（TDD）

### 純粋関数（`tests/test_toc_analyzer.py`）
- `is_chapter` 真: 「第1章…」「1章…」「１章」「第一章」「序章」「終章」
  「9章 おわりに」「Chapter 1」
- `is_chapter` 偽: 「第I部…」「第II部…」「参考文献」「訳者あとがき」「索引」
  「付録A」「はじめに」

### ダイアログ（`tests/test_pdf_toc_analyze_dialog.py`）
- 解析後は全行チェック済み、`selected_ranges == result_ranges`。
- 「章のみ」押下で部・巻末が外れ、`selected_ranges` が章行のみになる。
- 「全解除」で `selected_ranges == []` かつ Apply 非活性。
- 「章のみ」が0件一致のとき警告を出し、チェック状態を変えない。
- チェック手動変更で `selected_ranges` とサマリ・Apply 活性が追従。

### 統合（`tests/test_pdf_split_dialog.py`）
- `PdfSplitDialog` が `selected_ranges` を受け取り、章行だけを生成する。

## コンポーネント境界

- `is_chapter(name) -> bool`（toc_analyzer.py）: 純粋・テスト容易。何をするか＝
  見出し名が章かを判定。依存なし。
- `PdfTocAnalyzeDialog`: 選択UIと `selected_ranges` 提供。`is_chapter` に依存。
- `PdfSplitDialog`: `selected_ranges` を消費（内部は不変）。

## 選択状態の保持

- 再解析（`_run_analyze`）時は全チェックに戻す。手動選択は失われるが解析は通常
  1回なので許容。
- アンカー／前付けオプションの変更（`_recompute(reset_selection=False)`）では
  選択を保持する。名前ごとに出現順でチェック状態を対応させ、同名行も位置で区別。
  新規に現れた見出しはチェック済み（出力対象）にする。
- TOC 由来行の `explicit_end` は常に「次章の開始直前」を上限にクランプする。
  隣の行の開始を手前に動かしても章範囲は重複しない（ギャップは保持）。開始ページ
  を手動変更した行は固定終了を解除し、従来の連続モデルに戻る。

## 既知の制約（許容）

- 前付けオプションを OFF→ON し直すと、以前に手動で外した「前付け」行は再び
  チェック済みになる（前付けを出力対象に戻す操作とみなせるため妥当な挙動）。
- 判定ヒューリスティックの誤りは、行ごとチェックボックスでの手動修正で対応する。
