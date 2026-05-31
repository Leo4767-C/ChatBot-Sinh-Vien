"""
test_chat_formatters.py — Unit tests cho module chat_formatters.
Bao gồm: normalize_text, strip_md_prefix, wants_table_answer,
_parse_key_value_line, _looks_like_already_table, postprocess_answer, etc.
"""
import pytest
from app.routers.chat_formatters import (
    normalize_text, strip_md_prefix, wants_table_answer, postprocess_answer,
    _parse_key_value_line, _looks_like_already_table,
    _looks_like_short_uniform_lines, _to_table_from_pairs,
    _table_block_is_too_wide, _convert_table_block_to_bullets,
    _repair_broken_markdown_tables, _extract_short_lines,
)


class TestNormalizeText:
    def test_basic_vietnamese(self):
        assert normalize_text("Điểm chuẩn CNTT") == "diem chuan cntt"

    def test_unicode_accents_removed(self):
        result = normalize_text("Đại học Bách Khoa Hà Nội")
        assert result == "dai hoc bach khoa ha noi"

    def test_special_chars_removed(self):
        assert normalize_text("Điểm: 8.5/10!") == "diem 8 5 10"

    def test_d_stroke_preserved(self):
        """Regression test: đ (U+0111) phải thành 'd', không bị xóa."""
        assert normalize_text("đó") == "do"
        assert normalize_text("Đại") == "dai"
        assert normalize_text("điều") == "dieu"
        assert normalize_text("cái đó là gì") == "cai do la gi"

    def test_multiple_spaces_collapsed(self):
        assert normalize_text("hello   world") == "hello world"

    def test_empty_and_none(self):
        assert normalize_text("") == ""
        assert normalize_text(None) == ""

    def test_mixed_case(self):
        assert normalize_text("HỌC PHÍ năm 2024") == "hoc phi nam 2024"

    def test_whitespace_stripped(self):
        assert normalize_text("  xin chào  ") == "xin chao"


class TestStripMdPrefix:
    def test_dash_bullet(self):
        assert strip_md_prefix("- Nội dung") == "Nội dung"

    def test_asterisk_bullet(self):
        assert strip_md_prefix("* Nội dung") == "Nội dung"

    def test_number_dot(self):
        assert strip_md_prefix("1. Nội dung") == "Nội dung"

    def test_number_paren(self):
        assert strip_md_prefix("2) Nội dung") == "Nội dung"

    def test_unicode_bullet(self):
        assert strip_md_prefix("• Nội dung") == "Nội dung"

    def test_no_prefix(self):
        assert strip_md_prefix("Nội dung thuần") == "Nội dung thuần"

    def test_empty_and_none(self):
        assert strip_md_prefix("") == ""
        assert strip_md_prefix(None) == ""


class TestWantsTableAnswer:
    @pytest.mark.parametrize("q", [
        "Điểm chuẩn các ngành CNTT?",
        "Học phí năm 2024 là bao nhiêu?",
        "Chứng chỉ tiếng Anh tương đương?",
        "So sánh các chương trình đào tạo",
        "Danh sách các ngành tuyển sinh",
        "Trình bày dạng bảng",
        "Xếp loại học lực thế nào?",
    ])
    def test_positive(self, q):
        assert wants_table_answer(q) is True

    @pytest.mark.parametrize("q", [
        "Hôm nay trời đẹp quá",
        "Thầy ơi cho em hỏi",
        "Giải thích rõ hơn về bài tập",
    ])
    def test_negative(self, q):
        assert wants_table_answer(q) is False


class TestParseKeyValueLine:
    def test_colon(self):
        assert _parse_key_value_line("Ngành: CNTT") == ("Ngành", "CNTT")

    def test_dash(self):
        assert _parse_key_value_line("CNTT - 26.5") == ("CNTT", "26.5")

    def test_en_dash(self):
        assert _parse_key_value_line("Học phí – 15 triệu") == ("Học phí", "15 triệu")

    def test_no_separator(self):
        assert _parse_key_value_line("Chỉ là text") is None

    def test_with_bullet(self):
        assert _parse_key_value_line("- Mục: Chi tiết") == ("Mục", "Chi tiết")


class TestLooksLikeAlreadyTable:
    def test_standard_table(self, sample_table_answer):
        assert _looks_like_already_table(sample_table_answer) is True

    def test_non_table(self):
        assert _looks_like_already_table("Văn bản thường") is False

    def test_empty(self):
        assert _looks_like_already_table("") is False
        assert _looks_like_already_table(None) is False

    def test_pipe_without_separator(self):
        assert _looks_like_already_table("| A | B |\n| 1 | 2 |") is False


class TestLooksLikeShortUniformLines:
    def test_key_value_list(self):
        lines = ["Ngành: CNTT", "Điểm: 26.5", "Chỉ tiêu: 200", "TG: 4 năm"]
        assert _looks_like_short_uniform_lines(lines) is True

    def test_too_few(self):
        assert _looks_like_short_uniform_lines(["Một", "Hai"]) is False

    def test_too_many(self):
        assert _looks_like_short_uniform_lines([f"D{i}: x" for i in range(15)]) is False

    def test_line_too_long(self):
        assert _looks_like_short_uniform_lines(["A: B", "C: D", "X" * 200]) is False

    def test_empty(self):
        assert _looks_like_short_uniform_lines([]) is False


class TestToTableFromPairs:
    def test_basic(self):
        result = _to_table_from_pairs(["Ngành: CNTT", "Điểm: 26.5", "CT: 200"])
        assert result is not None
        assert "| Mục | Chi tiết |" in result

    def test_custom_headers(self):
        result = _to_table_from_pairs(["CNTT: 26.5", "KHMT: 27"], "Ngành", "Điểm")
        assert "| Ngành | Điểm |" in result

    def test_single_pair_none(self):
        assert _to_table_from_pairs(["Ngành: CNTT"]) is None

    def test_unparseable_none(self):
        assert _to_table_from_pairs(["Ngành: CNTT", "text thuần"]) is None


class TestExtractShortLines:
    def test_basic(self):
        text = "- CNTT: 26.5\n- KHMT: 27.0\n- KTPM: 25.8"
        assert len(_extract_short_lines(text)) == 3

    def test_skips_headings(self):
        lines = _extract_short_lines("# Title\n- A\n- B\n- C")
        assert not any(l.startswith("#") for l in lines)

    def test_returns_empty_for_table(self):
        assert _extract_short_lines("| C | D |\n|---|---|\n| A | B |") == []

    def test_empty(self):
        assert _extract_short_lines("") == []


class TestTableBlockIsTooWide:
    def test_normal(self):
        block = ["| A | B |", "|---|---|", "| 1 | 2 |"]
        assert _table_block_is_too_wide(block) is False

    def test_wide(self):
        block = ["| H |", "|---|", "| " + "X" * 230 + " |"]
        assert _table_block_is_too_wide(block) is True

    def test_too_many_rows(self):
        block = ["| H |", "|---|"] + [f"| R{i} |" for i in range(15)]
        assert _table_block_is_too_wide(block) is True

    def test_empty(self):
        assert _table_block_is_too_wide([]) is False


class TestConvertTableBlockToBullets:
    def test_basic(self):
        block = ["| Ngành | Điểm |", "|---|---|", "| CNTT | 26.5 |", "| KHMT | 27 |"]
        result = _convert_table_block_to_bullets(block)
        assert "**CNTT**" in result
        assert "26.5" in result

    def test_short_block(self):
        result = _convert_table_block_to_bullets(["| H |", "|---|"])
        assert "| H |" in result


class TestRepairBrokenMarkdownTables:
    def test_normal_table_kept(self, sample_table_answer):
        assert "|" in _repair_broken_markdown_tables(sample_table_answer)

    def test_non_table_unchanged(self):
        text = "Văn bản thường."
        assert _repair_broken_markdown_tables(text) == text

    def test_empty(self):
        assert _repair_broken_markdown_tables("") == ""


class TestPostprocessAnswer:
    def test_html_br_replaced(self):
        result = postprocess_answer("A<br>B<br/>C<br />D", "q")
        assert "<br" not in result

    def test_excessive_newlines(self):
        assert "\n\n\n" not in postprocess_answer("A\n\n\n\n\nB", "q")

    def test_cr_removed(self):
        assert "\r" not in postprocess_answer("A\r\nB", "q")

    def test_empty(self):
        assert postprocess_answer("", "q") == ""
        assert postprocess_answer(None, "q") == ""

    def test_stripped(self):
        assert postprocess_answer("  Nội dung  ", "q") == "Nội dung"

    def test_passthrough(self):
        assert postprocess_answer("Câu trả lời.", "q") == "Câu trả lời."
