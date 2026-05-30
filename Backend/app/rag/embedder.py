"""
embedder.py — Vector embedding service for the RAG pipeline.

Sử dụng mô hình BAAI/bge-m3 để tạo:
  • Dense vectors  → tìm kiếm ngữ nghĩa (semantic search)
  • Sparse vectors → tìm kiếm từ khóa (lexical / keyword search)
phục vụ Hybrid Search trong Qdrant.

Kiến trúc:
  ┌──────────────┐     ┌───────────┐     ┌────────┐
  │ Raw text     │ ──▸ │ Normalize │ ──▸ │ BGE-M3 │ ──▸ (dense, sparse)
  └──────────────┘     └───────────┘     └────────┘
"""
import logging
import unicodedata
from typing import Optional

from FlagEmbedding import BGEM3FlagModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MODEL_NAME = "BAAI/bge-m3"
_MAX_LENGTH = 8192  # BGE-M3 max sequence length (tokens)
_DEFAULT_BATCH_SIZE = 16

# ---------------------------------------------------------------------------
# Model management — lazy-loaded singleton
# ---------------------------------------------------------------------------
_model: Optional[BGEM3FlagModel] = None


def _get_model() -> BGEM3FlagModel:
    """Trả về model instance, tải lần đầu nếu chưa có (lazy init)."""
    global _model
    if _model is None:
        logger.info("⏳ Loading embedding model: %s ...", _MODEL_NAME)
        _model = BGEM3FlagModel(_MODEL_NAME, use_fp16=True)
        logger.info("✅ Embedding model loaded successfully.")
    return _model


def warmup() -> None:
    """
    Pre-load model tại thời điểm khởi động server.
    Gọi hàm này trong lifespan/startup event để tránh cold-start latency
    cho request đầu tiên.
    """
    _get_model()
    logger.info("🔥 Embedding model warmed up and ready.")


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------
def _normalize(text: str) -> str:
    """
    Chuẩn hóa văn bản trước khi embedding:
    - Unicode NFC normalization (quan trọng cho tiếng Việt,
      giúp thống nhất các ký tự tổ hợp như ă, ơ, ư)
    - Loại bỏ khoảng trắng / xuống dòng thừa
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    return " ".join(text.split()).strip()


# ---------------------------------------------------------------------------
# Core embedding API
# ---------------------------------------------------------------------------
def get_embeddings(
    texts: list[str],
    *,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> tuple[list, list[dict]]:
    """
    Chuyển đổi danh sách văn bản thành dense và sparse vectors.

    Args:
        texts:      Danh sách các đoạn văn bản cần embedding.
        batch_size: Số lượng text xử lý mỗi batch (tránh tràn GPU RAM).

    Returns:
        Tuple gồm 2 phần tử:
        - dense_vectors  (list[np.ndarray]) — mỗi phần tử là 1 vector 1024-d
        - sparse_vectors (list[dict])       — mỗi phần tử là dict {token_id: weight}
    """
    if not texts:
        logger.warning("get_embeddings() called with empty text list.")
        return [], []

    # 1. Chuẩn hóa text
    cleaned = [_normalize(t) for t in texts]

    # 2. Cảnh báo nếu có text quá dài (có thể bị truncate bởi model)
    for i, t in enumerate(cleaned):
        word_count = len(t.split())
        if word_count > _MAX_LENGTH:
            logger.warning(
                "Text index %d có ~%d từ, có thể vượt quá max length %d tokens "
                "và bị truncate. Hãy kiểm tra lại CHUNK_SIZE.",
                i, word_count, _MAX_LENGTH,
            )

    # 3. Encode — chỉ tính dense + sparse, KHÔNG tính ColBERT (tiết kiệm tài nguyên)
    output = _get_model().encode(
        cleaned,
        batch_size=batch_size,
        max_length=_MAX_LENGTH,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )

    dense_vecs = output["dense_vecs"]
    sparse_vecs = output["lexical_weights"]

    logger.debug(
        "Embedded %d texts → %d dense + %d sparse vectors.",
        len(texts), len(dense_vecs), len(sparse_vecs),
    )

    return dense_vecs, sparse_vecs