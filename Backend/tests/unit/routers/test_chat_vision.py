"""
test_chat_vision.py — Unit tests cho module chat_vision.

Bao gồm:
  - is_image_followup: phát hiện câu hỏi liên quan ảnh
  - is_text_focused_image_request: phát hiện yêu cầu đọc text từ ảnh
  - build_upload_image_prompt: xây dựng prompt cho ảnh upload
  - _parse_meta: parse metadata JSON
"""
import pytest
from app.routers.chat_vision import (
    is_image_followup,
    is_text_focused_image_request,
    build_upload_image_prompt,
    _parse_meta,
)


class TestIsImageFollowup:
    """Phát hiện câu hỏi tiếp theo liên quan đến ảnh."""

    @pytest.mark.parametrize("q", [
        "Trong ảnh này có gì?",
        "Xem hình này giúp em",
        "Bức ảnh có nội dung gì?",
        "Ảnh này nói về gì?",
        "Hình này cho thấy gì?",
        "Tấm ảnh đó có ý nghĩa gì?",
        "What is in this image?",
        "Describe this picture",
    ])
    def test_positive(self, q):
        assert is_image_followup(q) is True

    @pytest.mark.parametrize("q", [
        "Cho em hỏi về điểm chuẩn",
        "Giải thích thêm về ngành CNTT",
        "Hôm nay trời đẹp quá",
        "Tìm tài liệu giúp em",
    ])
    def test_negative(self, q):
        assert is_image_followup(q) is False


class TestIsTextFocusedImageRequest:
    """Phát hiện yêu cầu xử lý text từ ảnh (OCR, tóm tắt, dịch)."""

    @pytest.mark.parametrize("q", [
        "Tóm tắt nội dung ảnh",
        "Đọc chữ trong ảnh giúp em",
        "OCR ảnh này",
        "Dịch nội dung ảnh",
        "Ảnh ghi gì vậy?",
        "Nội dung văn bản trong ảnh là gì?",
        "Trích xuất text từ ảnh",
        "Ý chính của ảnh là gì?",
    ])
    def test_positive(self, q):
        assert is_text_focused_image_request(q) is True

    @pytest.mark.parametrize("q", [
        "Ảnh đẹp quá",
        "Cho xem thêm",
        "Ảnh có mấy người?",
    ])
    def test_negative(self, q):
        assert is_text_focused_image_request(q) is False


class TestBuildUploadImagePrompt:
    """Xây dựng prompt phù hợp cho ảnh upload."""

    def test_text_focused_prompt(self):
        prompt = build_upload_image_prompt("Tóm tắt nội dung ảnh")
        assert "PHẦN CHỮ" in prompt or "NỘI DUNG VĂN BẢN" in prompt
        assert "Tóm tắt nội dung ảnh" in prompt

    def test_general_prompt(self):
        prompt = build_upload_image_prompt("Ảnh này có gì?")
        assert "mô tả ảnh" in prompt.lower() or "tiếng Việt" in prompt

    def test_prompt_contains_user_question(self):
        q = "Hãy đọc nội dung văn bản"
        prompt = build_upload_image_prompt(q)
        assert q in prompt


class TestParseMeta:
    """Parse metadata JSON từ source_docs field."""

    def test_valid_json(self):
        raw = '{"sources": ["doc1.pdf"], "kind": "rag"}'
        result = _parse_meta(raw)
        assert result["sources"] == ["doc1.pdf"]
        assert result["kind"] == "rag"

    def test_none_input(self):
        assert _parse_meta(None) == {}

    def test_empty_string(self):
        assert _parse_meta("") == {}

    def test_invalid_json_fallback(self):
        """JSON lỗi → fallback tách bằng pipe."""
        result = _parse_meta("doc1.pdf|doc2.pdf")
        assert "sources" in result
        assert "doc1.pdf" in result["sources"]

    def test_non_dict_json(self):
        """JSON array → trả về dict rỗng."""
        assert _parse_meta("[1, 2, 3]") == {}

    def test_images_field(self):
        raw = '{"images": ["/images/uploads/abc.jpg"], "kind": "vision_upload"}'
        result = _parse_meta(raw)
        assert result["images"] == ["/images/uploads/abc.jpg"]
