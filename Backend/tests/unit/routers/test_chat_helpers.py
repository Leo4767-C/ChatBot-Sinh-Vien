"""
test_chat_helpers.py — Unit tests cho helper functions trong chat.py router.

Bao gồm:
  - _pack_meta: đóng gói metadata
  - _is_reference_source_name: phân biệt tên file tài liệu vs ảnh
  - _safe_chunk_text: trích xuất text an toàn từ Gemini response
"""
import json
import pytest
from unittest.mock import MagicMock

from app.routers.chat import _pack_meta, _is_reference_source_name, _safe_chunk_text


class TestPackMeta:
    """Đóng gói metadata thành JSON string."""

    def test_with_sources(self):
        result = _pack_meta(sources=["doc1.pdf", "doc2.pdf"])
        data = json.loads(result)
        assert data["sources"] == ["doc1.pdf", "doc2.pdf"]

    def test_with_images(self):
        result = _pack_meta(images=["/img/a.jpg"])
        data = json.loads(result)
        assert data["images"] == ["/img/a.jpg"]

    def test_with_kind(self):
        result = _pack_meta(kind="rag")
        data = json.loads(result)
        assert data["kind"] == "rag"

    def test_all_fields(self):
        result = _pack_meta(sources=["a"], images=["b"], kind="vision")
        data = json.loads(result)
        assert "sources" in data
        assert "images" in data
        assert data["kind"] == "vision"

    def test_empty_returns_none(self):
        assert _pack_meta() is None

    def test_empty_lists_return_none(self):
        """Empty lists/None → không thêm key → None."""
        assert _pack_meta(sources=None, images=None, kind=None) is None


class TestIsReferenceSourceName:
    """Phân biệt tên file tài liệu vs ảnh."""

    @pytest.mark.parametrize("name", [
        "quy_che_dao_tao.pdf",
        "document.docx",
        "thong_bao.txt",
        "chuong_trinh.md",
        "bao_cao.xlsx",
    ])
    def test_document_files(self, name):
        assert _is_reference_source_name(name) is True

    @pytest.mark.parametrize("name", [
        "image.png",
        "photo.jpg",
        "screenshot.jpeg",
        "logo.webp",
        "animation.gif",
        "icon.bmp",
    ])
    def test_image_files(self, name):
        assert _is_reference_source_name(name) is False

    def test_empty_name(self):
        assert _is_reference_source_name("") is False
        assert _is_reference_source_name("  ") is False


class TestSafeChunkText:
    """Trích xuất text an toàn từ Gemini streaming response."""

    def test_with_text_attribute(self):
        chunk = MagicMock()
        chunk.text = "Hello World"
        chunk.candidates = None
        assert _safe_chunk_text(chunk) == "Hello World"

    def test_with_candidates(self):
        part = MagicMock()
        part.text = "From candidate"
        content = MagicMock()
        content.parts = [part]
        candidate = MagicMock()
        candidate.content = content
        chunk = MagicMock()
        chunk.candidates = [candidate]
        assert _safe_chunk_text(chunk) == "From candidate"

    def test_empty_chunk(self):
        chunk = MagicMock()
        chunk.text = None
        chunk.candidates = []
        assert _safe_chunk_text(chunk) == ""

    def test_exception_handling(self):
        chunk = MagicMock()
        chunk.candidates = None
        chunk.text = None
        # Gây lỗi khi truy cập
        type(chunk).text = property(lambda s: (_ for _ in ()).throw(Exception))
        assert _safe_chunk_text(chunk) == ""

    def test_multiple_parts(self):
        part1 = MagicMock()
        part1.text = "Part 1 "
        part2 = MagicMock()
        part2.text = "Part 2"
        content = MagicMock()
        content.parts = [part1, part2]
        candidate = MagicMock()
        candidate.content = content
        chunk = MagicMock()
        chunk.candidates = [candidate]
        assert _safe_chunk_text(chunk) == "Part 1 Part 2"
