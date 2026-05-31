"""
test_chat_followup.py — Unit tests cho module chat_followup.

Bao gồm:
  - is_reference_followup: phát hiện câu hỏi tham chiếu
  - last_meaningful_model_answer / _last_meaningful_user_question
  - extract_referenced_item: trích xuất nội dung tham chiếu
  - rewrite_followup_question: viết lại câu hỏi follow-up
  - estimate_tokens: ước tính token
  - trim_history_by_token_budget: cắt history theo budget
"""
import pytest
from app.routers.chat_followup import (
    is_reference_followup,
    last_meaningful_model_answer,
    _last_meaningful_user_question,
    extract_referenced_item,
    rewrite_followup_question,
    estimate_tokens,
    trim_history_by_token_budget,
    HISTORY_TOKEN_BUDGET,
)


# ═══════════════════════════════════════════════════════════════════════════════
# is_reference_followup
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsReferenceFollowup:
    """Phát hiện câu hỏi tham chiếu nội dung trước đó."""

    @pytest.mark.parametrize("q", [
        "Ý số 2 là gì?",
        "Mục 3 nói về gì?",
        "Giải thích thêm",           # matches "giai thich them"
        "Giải thích rõ hơn",         # matches "giai thich ro hon"
        "Giải thích cụ thể hơn",     # matches "giai thich cu the hon"
        "Nó là gì?",                 # matches "no la gi"
        "Nó có nghĩa gì?",           # matches "no co nghia"
        "Về việc này em chưa hiểu",  # matches "ve viec nay"
        "Ý thứ nhất là gì?",         # matches "y thu nhat"
        "Ý thứ hai là gì?",          # matches "y thu hai"
        "Ý trên nói gì?",            # matches "y tren"
        "Mục trên là gì?",           # matches "muc tren"
    ])
    def test_positive_cases(self, q):
        assert is_reference_followup(q) is True

    @pytest.mark.parametrize("q", [
        "Điểm chuẩn ngành CNTT là bao nhiêu?",
        "Cho em hỏi về học phí",
        "Hôm nay trời đẹp quá",
        "Thầy ơi dạy em lập trình",
        "Em muốn đăng ký ngành gì?",
    ])
    def test_negative_cases(self, q):
        assert is_reference_followup(q) is False


# ═══════════════════════════════════════════════════════════════════════════════
# last_meaningful_model_answer / _last_meaningful_user_question
# ═══════════════════════════════════════════════════════════════════════════════

class TestLastMeaningfulMessages:
    def test_model_answer(self, sample_chat_history):
        answer = last_meaningful_model_answer(sample_chat_history)
        assert "Công nghệ thông tin" in answer
        assert "26.5" in answer

    def test_model_answer_skips_empty(self):
        history = [
            {"role": "model", "content": "Câu trả lời thật"},
            {"role": "model", "content": ""},
            {"role": "model", "content": "   "},
        ]
        assert last_meaningful_model_answer(history) == "Câu trả lời thật"

    def test_model_answer_empty_history(self):
        assert last_meaningful_model_answer([]) == ""
        assert last_meaningful_model_answer(None) == ""

    def test_user_question(self, sample_chat_history):
        q = _last_meaningful_user_question(sample_chat_history)
        assert "Điểm chuẩn" in q

    def test_user_question_empty(self):
        assert _last_meaningful_user_question([]) == ""
        assert _last_meaningful_user_question(None) == ""


# ═══════════════════════════════════════════════════════════════════════════════
# extract_referenced_item
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractReferencedItem:
    """Trích xuất mục được tham chiếu từ câu trả lời trước."""

    def test_extract_by_number(self, sample_chat_history):
        prev = sample_chat_history[1]["content"]
        result = extract_referenced_item("Ý số 2 là gì?", prev)
        assert result != ""
        assert "Khoa học máy tính" in result or "2" in result

    def test_extract_by_number_with_proper_heading(self):
        """Test với heading format chuẩn (không bị strip_md_prefix xóa)."""
        prev = (
            "Ý 1: Điều kiện đầu vào\n"
            "Cần có bằng tốt nghiệp THPT.\n"
            "Ý 2: Hồ sơ xét tuyển\n"
            "Cần nộp đầy đủ giấy tờ.\n"
            "Ý 3: Thời hạn\n"
            "Hạn nộp hồ sơ trước 30/6."
        )
        result = extract_referenced_item("Ý số 1 là gì?", prev)
        # Should find block starting with "Ý 1"
        assert result != ""

    def test_generic_reference_y_tren(self):
        """'ý trên' → fallback lấy top meaningful lines."""
        prev = (
            "Công nghệ thông tin là ngành đào tạo.\n"
            "Sinh viên được học lập trình, cơ sở dữ liệu.\n"
            "Thời gian đào tạo 4 năm.\n"
        )
        result = extract_referenced_item("Ý trên nói gì?", prev)
        assert result != ""

    def test_no_reference_empty_answer(self):
        result = extract_referenced_item("Ý số 1 là gì?", "")
        assert result == ""

    def test_no_match_returns_empty(self):
        result = extract_referenced_item(
            "Ý số 99 là gì?",
            "1. Mục A\n2. Mục B\n3. Mục C",
        )
        # No heading "99." found, fallback searches for "99" in lines
        assert result == ""


# ═══════════════════════════════════════════════════════════════════════════════
# rewrite_followup_question
# ═══════════════════════════════════════════════════════════════════════════════

class TestRewriteFollowupQuestion:
    """Viết lại câu hỏi follow-up có ngữ cảnh."""

    def test_non_followup_unchanged(self):
        q = "Điểm chuẩn ngành CNTT?"
        assert rewrite_followup_question(q, []) == q

    def test_followup_with_reference(self, sample_chat_history):
        q = "Ý số 2 là gì?"
        result = rewrite_followup_question(q, sample_chat_history)
        assert result != q
        assert "Ý số 2" in result or "Khoa học máy tính" in result

    def test_followup_with_context_but_no_item(self):
        history = [
            {"role": "user", "content": "Giới thiệu ngành CNTT"},
            {"role": "model", "content": "CNTT là ngành hot."},
        ]
        q = "Giải thích thêm"
        result = rewrite_followup_question(q, history)
        assert result != q
        assert "CNTT" in result or "Tiếp nối" in result

    def test_followup_empty_history(self):
        q = "Giải thích thêm"
        result = rewrite_followup_question(q, [])
        # Không có context → giữ nguyên
        assert result == q


# ═══════════════════════════════════════════════════════════════════════════════
# estimate_tokens
# ═══════════════════════════════════════════════════════════════════════════════

class TestEstimateTokens:
    def test_basic(self):
        assert estimate_tokens("hello world") > 0

    def test_empty(self):
        assert estimate_tokens("") == 1  # max(1, 0)

    def test_long_text(self):
        text = "word " * 1000
        tokens = estimate_tokens(text)
        assert tokens > 100

    def test_proportional(self):
        short = estimate_tokens("abc")
        long = estimate_tokens("abc " * 100)
        assert long > short


# ═══════════════════════════════════════════════════════════════════════════════
# trim_history_by_token_budget
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrimHistoryByTokenBudget:
    def test_short_history_unchanged(self, sample_chat_history):
        result = trim_history_by_token_budget(sample_chat_history)
        assert len(result) == len(sample_chat_history)

    def test_long_history_trimmed(self, long_history):
        result = trim_history_by_token_budget(long_history, budget=500)
        assert len(result) < len(long_history)

    def test_keeps_head_messages(self, long_history):
        result = trim_history_by_token_budget(long_history, budget=500)
        # Luôn giữ 2 tin đầu
        assert result[0] == long_history[0]
        assert result[1] == long_history[1]

    def test_keeps_tail_messages(self, long_history):
        result = trim_history_by_token_budget(long_history, budget=2000)
        # Tin cuối cùng nên được giữ (nếu đủ budget)
        assert result[-1] == long_history[-1]

    def test_empty_history(self):
        assert trim_history_by_token_budget([]) == []

    def test_budget_zero(self):
        history = [{"role": "user", "content": "test"}]
        result = trim_history_by_token_budget(history, budget=0)
        # Budget = 0 thì head vẫn được keep, tail budget âm → empty tail
        assert len(result) <= 2

    def test_custom_budget(self, sample_chat_history):
        result = trim_history_by_token_budget(sample_chat_history, budget=100_000)
        assert len(result) == len(sample_chat_history)
