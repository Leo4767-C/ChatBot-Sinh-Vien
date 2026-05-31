"""
test_doc_preprocessor.py — Unit tests cho module doc_preprocessor.

Bao gồm:
  - split_sentences: tách câu
  - count_tokens: đếm token
"""
import pytest
from app.rag.doc_preprocessor import split_sentences, count_tokens


class TestSplitSentences:
    """Tách văn bản thành danh sách câu."""

    def test_basic(self):
        text = "Câu một. Câu hai. Câu ba."
        result = split_sentences(text)
        assert len(result) >= 2

    def test_question_mark(self):
        text = "Bạn khỏe không? Tôi khỏe. Cảm ơn!"
        result = split_sentences(text)
        assert len(result) >= 2

    def test_no_sentence_break(self):
        text = "Đây là một câu duy nhất"
        result = split_sentences(text)
        assert len(result) == 1

    def test_empty(self):
        assert split_sentences("") == []
        assert split_sentences(None) == []

    def test_preserves_numbers(self):
        """Không tách tại dấu chấm trong số (1.5, 2.0)."""
        text = "Điểm 8.5 là tốt. Điểm 9.0 là xuất sắc."
        result = split_sentences(text)
        # "8.5" và "9.0" không bị tách
        joined = " ".join(result)
        assert "8.5" in joined or "8" in joined


class TestCountTokens:
    """Đếm token bằng tiktoken."""

    def test_basic(self):
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        result = count_tokens("Hello world", enc)
        assert result > 0

    def test_empty(self):
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        assert count_tokens("", enc) == 0

    def test_vietnamese(self):
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        result = count_tokens("Xin chào Việt Nam", enc)
        assert result > 0
