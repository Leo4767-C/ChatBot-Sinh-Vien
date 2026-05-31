"""
test_config.py — Unit tests cho module config.

Bao gồm:
  - Settings defaults
  - EFFECTIVE_GEMINI_API_KEY property
  - Field validator
"""
import os
import pytest
from app.core.config import Settings


class TestSettings:
    """Kiểm tra cấu hình mặc định và validation."""

    def test_defaults(self):
        s = Settings(
            GEMINI_API_KEY="test-key",
            _env_file=None,  # Không đọc .env
        )
        assert s.GEMINI_MODEL == "gemini-2.5-flash"
        assert s.CHUNK_SIZE == 800
        assert s.OVERLAP == 100
        assert s.EMBEDDING_VECTOR_SIZE == 1024
        assert s.DEVICE == "cpu"
        assert s.TEMPERATURE == 0.7
        assert s.MAX_OUTPUT_TOKENS == 4096

    def test_effective_key_from_google(self):
        s = Settings(
            GOOGLE_API_KEY="google-key",
            GEMINI_API_KEY="gemini-key",
            _env_file=None,
        )
        # GOOGLE_API_KEY ưu tiên hơn
        assert s.EFFECTIVE_GEMINI_API_KEY == "google-key"

    def test_effective_key_from_gemini(self):
        s = Settings(
            GOOGLE_API_KEY=None,
            GEMINI_API_KEY="gemini-key",
            _env_file=None,
        )
        assert s.EFFECTIVE_GEMINI_API_KEY == "gemini-key"

    def test_effective_key_raises_when_missing(self):
        s = Settings(
            GOOGLE_API_KEY=None,
            GEMINI_API_KEY=None,
            _env_file=None,
        )
        with pytest.raises(ValueError, match="Cần GOOGLE_API_KEY"):
            _ = s.EFFECTIVE_GEMINI_API_KEY

    def test_model_validator_strips_whitespace(self):
        s = Settings(
            GEMINI_API_KEY="key",
            GEMINI_MODEL="  gemini-2.5-flash  ",
            _env_file=None,
        )
        assert s.GEMINI_MODEL == "gemini-2.5-flash"

    def test_qdrant_defaults(self):
        s = Settings(GEMINI_API_KEY="key", _env_file=None)
        assert s.QDRANT_URL == "http://localhost:6333"
        assert s.QDRANT_COLLECTION == "nckh_docs"
        assert s.COLLECTION_NAME == "nckh_docs"
