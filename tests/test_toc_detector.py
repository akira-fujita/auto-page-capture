# tests/test_toc_detector.py
"""目次ページ・本文見出しからの章検出（純ロジック）のテスト"""

from src.export.toc_detector import detect_chapters_from_text, has_text_layer


def test_detects_chapter_headings_in_body():
    """本文の「第N章」見出しから物理ページを検出する"""
    page_texts = [
        "表紙",
        "第1章 はじめに\n\n本文本文本文",
        "本文のつづき",
        "第2章 設計\n\n本文本文",
        "本文のつづき",
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.source == "heading"
    assert result.chapters == [("第1章 はじめに", 2), ("第2章 設計", 4)]


def test_normalizes_fullwidth_digits_and_spaces():
    """全角数字・全角空白の見出しも検出する"""
    page_texts = [
        "表紙",
        "第１章　はじめに",
        "第２章　設計",
    ]
    result = detect_chapters_from_text(page_texts)
    assert [c[1] for c in result.chapters] == [2, 3]


def test_detects_kanji_numeral_chapters():
    """漢数字の章番号を検出する"""
    page_texts = [
        "表紙",
        "第一章 序論",
        "本文",
        "第二章 本論",
        "第十一章 補遺",
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.chapters == [
        ("第一章 序論", 2),
        ("第二章 本論", 4),
        ("第十一章 補遺", 5),
    ]


def test_detects_english_chapter_headings():
    """Chapter N 形式の見出しを検出する"""
    page_texts = [
        "Cover",
        "Chapter 1 Introduction",
        "body",
        "CHAPTER 2  Design",
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.chapters == [("Chapter 1 Introduction", 2), ("CHAPTER 2  Design", 4)]


def test_rejects_inline_chapter_references():
    """本文中の言及（句読点を含む行）は見出しとして扱わない"""
    page_texts = [
        "第3章では詳しく述べる。",
        "第1章 はじめに",
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.chapters == [("第1章 はじめに", 2)]


def test_rejects_long_lines():
    """40文字を超える行は見出しとして扱わない"""
    page_texts = [
        "第1章 はじめに",
        "第2章 " + "あ" * 60,
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.chapters == [("第1章 はじめに", 1)]


def test_running_header_uses_first_occurrence():
    """柱（実行ヘッダ）が続いても章の初出ページを返す"""
    page_texts = [
        "表紙",
        "第1章 基礎\n本文",
        "第1章 基礎\n本文のつづき",
        "第1章 基礎\n本文のつづき",
        "第2章 応用\n本文",
        "第2章 応用\n本文のつづき",
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.chapters == [("第1章 基礎", 2), ("第2章 応用", 5)]


def test_drops_entries_breaking_strict_page_increase():
    """開始ページが厳密増加しない候補は破棄する"""
    # 第2章が第3章より後ろのページに現れる矛盾したケース
    page_texts = [
        "第1章 A",
        "第3章 C",
        "第2章 B",
    ]
    result = detect_chapters_from_text(page_texts)
    # 章番号昇順で厳密増加を満たすのは 第1章(p.1) → 第3章(p.2) のみ
    assert result.chapters == [("第1章 A", 1), ("第3章 C", 2)]


def test_toc_page_is_excluded_from_body_scan():
    """目次ページ自体は章の開始ページとして採用しない"""
    toc = "目次\n第1章 はじめに ...... 1\n第2章 設計 ...... 20\n第3章 実装 ...... 40"
    page_texts = [
        "表紙",
        toc,
        "第1章 はじめに",
        "第2章 設計",
        "第3章 実装",
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.source == "heading"
    assert result.chapters == [
        ("第1章 はじめに", 3),
        ("第2章 設計", 4),
        ("第3章 実装", 5),
    ]


def test_toc_title_completes_chapter_name():
    """章名は目次のタイトルを優先する（本文見出しより情報量が多い）"""
    toc = "目次\n第1章 はじめに ― 本書の狙い ...... 1\n第2章 設計の原則 ...... 20"
    page_texts = [
        toc,
        "第1章",
        "第2章",
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.chapters == [
        ("第1章 はじめに ― 本書の狙い", 2),
        ("第2章 設計の原則", 3),
    ]


def test_detects_multi_page_toc():
    """多段（複数ページ）の目次を検出して本文走査から除外する"""
    toc1 = "目次\n第1章 A ...... 1\n第2章 B ...... 10\n第3章 C ...... 20"
    toc2 = "第4章 D ...... 30\n第5章 E ...... 40"
    page_texts = [
        toc1,
        toc2,
        "第1章 A",
        "第2章 B",
        "第3章 C",
        "第4章 D",
        "第5章 E",
    ]
    result = detect_chapters_from_text(page_texts)
    assert [c[1] for c in result.chapters] == [3, 4, 5, 6, 7]


def test_falls_back_to_printed_toc_pages():
    """本文見出しが取れない場合は目次の印字ページ番号を返す"""
    toc = "目次\n第1章 はじめに ...... 3\n第2章 設計 ...... 5"
    page_texts = [
        toc,
        "（見出しが画像のページ）",
        "本文",
        "本文",
        "本文",
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.source == "toc"
    assert result.chapters == [("第1章 はじめに", 3), ("第2章 設計", 5)]


def test_toc_fallback_drops_out_of_range_pages():
    """目次フォールバックで文書範囲外のページは破棄する"""
    toc = "目次\n第1章 はじめに ...... 2\n第2章 設計 ...... 999"
    page_texts = [toc, "本文", "本文"]
    result = detect_chapters_from_text(page_texts)
    assert result.chapters == [("第1章 はじめに", 2)]


def test_contents_word_in_body_is_not_toc():
    """本文中に contents の語があるだけのページは目次扱いしない"""
    page_texts = [
        "Chapter 1 Introduction\nThe contents of this book are organized as follows "
        "and we will explore each of them in detail",
        "Chapter 2 Design",
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.chapters == [("Chapter 1 Introduction", 1), ("Chapter 2 Design", 2)]


def test_returns_none_source_when_nothing_detected():
    """章が検出できない場合は空リストと source='none'（空入力も同様）"""
    result = detect_chapters_from_text(["本文だけのページ", "章の手がかりがない"])
    assert result.chapters == []
    assert result.source == "none"

    empty = detect_chapters_from_text([])
    assert empty.chapters == []
    assert empty.source == "none"


def test_has_text_layer():
    """テキストが実質空ならテキスト層なし、十分な文字数があればありと判定する"""
    assert has_text_layer(["", "  \n ", ""]) is False
    assert has_text_layer(["これは本文のテキストです" * 5, "つづき" * 20]) is True


def test_drops_duplicate_start_pages():
    """同じページに複数章が割り当たる場合、後続を破棄する（分割不能な設定を作らない）"""
    page_texts = [
        "表紙",
        "第1章 A\n第2章 B",
        "本文",
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.chapters == [("第1章 A", 2)]


def test_outlier_reference_does_not_discard_real_chapters():
    """前付けの「第10章を参照」のような外れ値1件で本物の章を捨てない"""
    page_texts = [
        "まえがき\n第10章を参照",
        "第1章 A",
        "第2章 B",
        "第3章 C",
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.chapters == [("第1章 A", 2), ("第2章 B", 3), ("第3章 C", 4)]


def test_outlier_heading_does_not_poison_sequence():
    """見出し形の外れ値が前方にあっても、最長の整合列を採用する"""
    page_texts = [
        "第10章 付録",   # 前付けに紛れた外れ値
        "第1章 A",
        "第2章 B",
        "第3章 C",
    ]
    result = detect_chapters_from_text(page_texts)
    assert result.chapters == [("第1章 A", 2), ("第2章 B", 3), ("第3章 C", 4)]


def test_multi_page_toc_with_single_entry_last_page():
    """目次の最終ページがエントリ1行だけでも目次として除外する"""
    toc1 = "目次\n第1章 A ...... 1\n第2章 B ...... 10\n第3章 C ...... 20"
    toc2 = "第4章 D ...... 30\n第5章 E ...... 40"
    toc3 = "第6章 付録 ...... 50"
    page_texts = [
        toc1,
        toc2,
        toc3,
        "第1章 A",
        "第2章 B",
        "第3章 C",
        "第4章 D",
        "第5章 E",
        "第6章 付録",
    ]
    result = detect_chapters_from_text(page_texts)
    assert [c[1] for c in result.chapters] == [4, 5, 6, 7, 8, 9]


def test_toc_search_is_limited_to_front_matter():
    """巻末の短い『Contents Analysis』のような行を目次と誤判定しない"""
    page_texts = ["第1章 A"] + [f"本文{i}" for i in range(40)]
    # 巻末付近の章ページに短い "Contents Analysis" 行が混ざっているケース
    page_texts.append("Contents Analysis\n第2章 B")
    result = detect_chapters_from_text(page_texts)
    assert result.chapters == [("第1章 A", 1), ("第2章 B", len(page_texts))]
