"""
test_embedder.py — Unit tests cho module embedder.

Sử dụng mock cho BGE-M3 model (tránh load model ~2GB khi chạy test).
Bao gồm:
  - _normalize: chuẩn hóa Unicode NFC
  - get_embeddings: API chính
  - warmup: pre-load model
"""
import pytest
from unittest.mock import MagicMock, patch

from app.rag.embedder import _normalize, get_embeddings, warmup, _get_model


class TestNormalize:
    """Chuẩn hóa text trước khi embedding."""

    def test_basic(self):
        assert _normalize("Hello  World") == "Hello World"

    def test_unicode_nfc(self):
        """Tiếng Việt: NFC normalization giữ nguyên dấu."""
        result = _normalize("Việt Nam")
        assert "Việt" in result
        assert "Nam" in result

    def test_newlines_removed(self):
        assert _normalize("Line1\nLine2\tLine3") == "Line1 Line2 Line3"

    def test_empty(self):
        assert _normalize("") == ""
        assert _normalize(None) == ""

    def test_whitespace_collapse(self):
        assert _normalize("  a   b   c  ") == "a b c"


class TestGetEmbeddings:
    """API chính — trả về (dense, sparse) vectors."""

    @patch("app.rag.embedder._get_model")
    def test_empty_input(self, mock_model):
        dense, sparse = get_embeddings([])
        assert dense == []
        assert sparse == []
        mock_model.assert_not_called()

    @patch("app.rag.embedder._get_model")
    def test_basic_embedding(self, mock_model):
        mock_instance = MagicMock()
        mock_instance.encode.return_value = {
            "dense_vecs": [[0.1] * 1024],
            "lexical_weights": [{"1": 0.5}],
        }
        mock_model.return_value = mock_instance

        dense, sparse = get_embeddings(["Test text"])
        assert len(dense) == 1
        assert len(sparse) == 1
        assert len(dense[0]) == 1024

    @patch("app.rag.embedder._get_model")
    def test_batch_embedding(self, mock_model):
        mock_instance = MagicMock()
        mock_instance.encode.return_value = {
            "dense_vecs": [[0.1] * 1024, [0.2] * 1024, [0.3] * 1024],
            "lexical_weights": [{"1": 0.5}, {"2": 0.6}, {"3": 0.7}],
        }
        mock_model.return_value = mock_instance

        texts = ["Text 1", "Text 2", "Text 3"]
        dense, sparse = get_embeddings(texts)
        assert len(dense) == 3
        assert len(sparse) == 3

    @patch("app.rag.embedder._get_model")
    def test_normalizes_input(self, mock_model):
        """Đảm bảo text được normalize trước khi encode."""
        mock_instance = MagicMock()
        mock_instance.encode.return_value = {
            "dense_vecs": [[0.1]],
            "lexical_weights": [{}],
        }
        mock_model.return_value = mock_instance

        get_embeddings(["  Hello\n\nWorld  "])
        call_args = mock_instance.encode.call_args
        # Text đầu tiên được cleaned
        cleaned_texts = call_args[0][0]
        assert cleaned_texts[0] == "Hello World"

    @patch("app.rag.embedder._get_model")
    def test_encode_params(self, mock_model):
        """Kiểm tra params gọi model.encode đúng."""
        mock_instance = MagicMock()
        mock_instance.encode.return_value = {
            "dense_vecs": [[0.1]],
            "lexical_weights": [{}],
        }
        mock_model.return_value = mock_instance

        get_embeddings(["test"], batch_size=8)
        call_kwargs = mock_instance.encode.call_args[1]
        assert call_kwargs["return_dense"] is True
        assert call_kwargs["return_sparse"] is True
        assert call_kwargs["return_colbert_vecs"] is False
        assert call_kwargs["batch_size"] == 8


class TestWarmup:
    @patch("app.rag.embedder._get_model")
    def test_warmup_calls_get_model(self, mock_model):
        warmup()
        mock_model.assert_called_once()
