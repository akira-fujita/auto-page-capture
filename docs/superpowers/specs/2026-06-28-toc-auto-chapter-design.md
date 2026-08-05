# 目次自動解析による章分割 — 設計

作成日: 2026-06-28
ブランチ: `claude/toc-auto-chapter`

## 背景・目的

現状、キャプチャ→章分割フロー(`ChapterDialog`)では、ユーザーがサムネイルをクリックして
章境界を1つずつ手動で指定する必要がある。本のどのページが何枚目かを自分で数える手間が大きい。

本機能では、**キャプチャ済みの目次ページ画像を `claude` CLI に解析させ**、章名と印刷ページ番号を
抽出し、章境界を自動で算出する。ユーザーは目視で確認・修正してから確定できる。

### 解決する難しさ

- 目次は複数ページにまたがる → 複数キャプチャ画像をまとめて解析する。
- 目次のフォーマットは本ごとに異なる → ルール解析ではなく `claude` CLI(マルチモーダル)に判定させ、
  フォーマット差を吸収する。
- 目次の「印刷ページ番号」と「キャプチャ枚数」はズレる(表紙・まえがき・目次の分) →
  アンカー1点をユーザーが指定し、offset で全章を換算する。

## 方針決定(ブレインストーミング結果)

| 論点 | 決定 |
|---|---|
| 解析エンジン | **B: `claude` CLI に判定させる**(従量課金なし=サブスク枠 / フォーマット差に最も強い)。A(Vision OCR+ルール)のフォールバックは今回なし。 |
| 画像の取込元 | **キャプチャ済画像から選ぶ**(`ChapterDialog` のサムネイル番号で範囲指定) |
| ページズレ補正 | **アンカー1点を手動指定**(`offset = アンカーのキャプチャ枚数 − その印刷ページ番号`) |
| スコープ | **キャプチャフロー(`ChapterDialog`)のみ**。既存PDF分割への展開は将来 `toc_analyzer.py` 再利用で対応(YAGNI) |

`claude` CLI はオンデバイスではなく Anthropic サーバへ画像を送るためネットワークが必要。
ただし従量 API 課金は発生せずサブスク枠で動く。

## アーキテクチャ

ロジックを純粋・テスト可能に保つため3層に分ける(既存 `PdfGenerator` が OCR エンジンを注入できる構造に倣う)。

```
ChapterDialog (既存)
   └─[ボタン]「目次から章を自動解析」
        └─ TocAnalyzeDialog (新規UI・薄い)
             ├─ ClaudeTocEngine (新規・注入可/モック可) … claude CLI 呼び出し
             └─ toc_logic (新規・純粋関数)            … offset計算・章変換
        ← 章リスト(list[Chapter]) を返して ChapterDialog に反映
```

### 新規モジュール: `src/export/toc_analyzer.py`

```python
@dataclass
class TocEntry:
    name: str
    printed_page: int

class ClaudeTocEngine:
    def analyze(self, image_paths: list[Path]) -> list[TocEntry]: ...
        # claude -p --output-format json をヘッドレス実行し画像を読ませてJSON抽出

# 純粋関数
def compute_offset(anchor_capture_no: int, anchor_printed_page: int) -> int:
    return anchor_capture_no - anchor_printed_page

def entries_to_chapters(
    entries: list[TocEntry], offset: int, total_pages: int
) -> tuple[list[Chapter], list[str]]:
    # 印刷ページ→0始まりキャプチャindexへ変換、start でソート、
    # end = 次章.start - 1、最終章は total_pages - 1。
    # 範囲外(<0 または >= total_pages)の行は除外し、警告メッセージを返す。
```

`Chapter` は既存 `src/ui/chapter_dialog.py` の dataclass を再利用(`name`, `start` 0始まり, `end` 0始まり包含)。

## データフロー

例: 表紙・まえがき・目次があり、本文 p.1 がキャプチャ8枚目から始まる本。

```
目次の記載:  「第2章 …… 45」  (printed_page = 45)
アンカー指定: 印刷 p.1 = キャプチャ #8
   → offset = 8 - 1 = 7
変換:        capture_no(printed 45) = 45 + 7 = 52  (1始まり)
   → Chapter.start = 52 - 1 = 51  (0始まり)
```

- 変換後に `start` でソートし、各章 `end = 次章.start - 1`、最終章 `end = total_pages - 1`。
- 変換結果が `< 0` / `>= total_pages` の行は範囲外として除外し、警告に列挙する
  (目次OCR誤りやアンカーミスの検知になる)。

## UX: TocAnalyzeDialog

`ChapterDialog` にボタンを1つ追加し、押すと専用ダイアログを開く(`ChapterDialog` 本体はほぼ無改修)。

```
┌─ 目次から章を自動解析 ────────────────────┐
│ ① 目次のページ範囲                          │
│    キャプチャ #[ 5 ] 〜 #[ 6 ]   ← 複数ページ可  │
│                                              │
│ ② ページ番号アンカー(ズレ補正)            │
│    印刷 p.[ 1 ]  =  キャプチャ #[ 8 ]         │
│                                              │
│         [ 解析する ]   ← claude CLI 実行(待機カーソル) │
│ ─────────────────────────────────────────── │
│ ③ 結果プレビュー(編集可)                   │
│   章名            印刷p   → キャプチャ範囲     │
│   第1章           1       p.8-51             │
│   第2章           45      p.52-...           │
│   ⚠ 「付録」 320 → 範囲外のため除外          │
│                                              │
│        [ キャンセル ]  [ この内容で章を設定 ] │
└──────────────────────────────────────────────┘
```

- ①②は既存サムネイルの番号(`p.N` 表示)をそのまま使うので迷いにくい。
- ③で目視確認・手直ししてから確定 → `ChapterDialog.chapters` を置き換えて再描画。
  OCR/解析が多少外しても安全。

## claude CLI 呼び出し詳細

- コマンド: `claude -p --output-format json "<指示>"` を `subprocess` で実行。
  指示文に画像パスを列挙し「これらは本の目次。各章タイトルと印刷ページ番号を抽出し、
  `[{"name":..,"page":..}]` の JSON のみ出力」と指定。
- 出力の `result` から JSON 配列を `json.loads`。コードブロック等の混入に備え、
  最初の `[` 〜 最後の `]` を抜き出すフォールバック抽出を入れる。
- タイムアウトを設定(例: 120秒)。

### 失敗系の扱い(Aフォールバックなし)

| 失敗 | 検知 | ユーザー向けメッセージ |
|---|---|---|
| CLI 未インストール | `FileNotFoundError` | `claude` CLI が見つからない旨 + 手動入力に戻れる案内 |
| タイムアウト | `subprocess.TimeoutExpired` | 時間切れ。再試行 or 手動入力の案内 |
| JSON パース不可 | `json.JSONDecodeError` / 抽出失敗 | 解析結果を読めなかった旨 + 手動入力の案内 |

> 実装時に `claude -p` が画像パスを Read できることを実機で確認する。
> できなければ画像を base64 で渡す等の代替を検討。

## テスト方針(TDD)

| テスト対象 | 方法 |
|---|---|
| `compute_offset` / `entries_to_chapters` | 純粋関数。境界(範囲外除外・ソート・最終章 end・重複ページ)を網羅 |
| `ClaudeTocEngine` の JSON パース | `subprocess` をモックし、正常 / コードブロック付き / 壊れた JSON を検証 |
| `TocAnalyzeDialog` | エンジンをモック注入し、結果反映・警告表示・確定時の章リスト返却を検証(既存 `tests/test_chapter_dialog.py` に倣う) |

実機の `claude` CLI 呼び出し(ネットワーク依存)は自動テストに含めず、手動確認とする。

## レビュー

- 実装は TDD(テスト先行)で進める。
- 節目および実装完了後に **Codex レビュー** をかける(差分レビュー)。

## 影響範囲・非対象

- 変更: `src/ui/chapter_dialog.py`(ボタン追加と結果反映のみ)、新規 `src/export/toc_analyzer.py`、
  新規 `src/ui/toc_analyze_dialog.py`、新規テスト。
- 非対象: 既存PDF分割(`PdfSplitDialog`)への展開、Vision OCR フォールバック。
- ドキュメント: 実装完了後に `README.md` の機能一覧へ追記する。
