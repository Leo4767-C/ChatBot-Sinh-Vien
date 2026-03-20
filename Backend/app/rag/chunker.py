import re

import tiktoken
from typing import List

from app.core.config import settings


def get_tokenizer(model_name: str):
    """
    Trả về tokenizer tương thích với model_name.
    Với Gemini: dùng cl100k_base làm xấp xỉ vì Gemini không có tiktoken chính thức.
    """
    if re.search(r"gpt|text-embedding", model_name):
        try:
            return tiktoken.encoding_for_model(model_name)
        except KeyError:
            print(f"[WARN] Model {model_name} không được hỗ trợ chính thức. Dùng tokenizer mặc định (cl100k_base).")
            return tiktoken.get_encoding("cl100k_base")

    if "gemini" in model_name:
        # Gemini không có tiktoken — dùng cl100k_base làm xấp xỉ (tốt hơn SimpleTokenizer không có encode/decode)
        print(f"[INFO] Dùng tokenizer xấp xỉ cl100k_base cho model {model_name} (Gemini không có tiktoken).")
        return tiktoken.get_encoding("cl100k_base")

    print(f"[WARN] Model {model_name} không xác định, dùng tokenizer mặc định.")
    return tiktoken.get_encoding("cl100k_base")


def estimate_max_tokens_per_chunk(model_name: str, reserve_tokens: int = 5000) -> int:
    """
    Tính toán số token tối đa cho mỗi chunk dựa theo model và số chunk cần lấy (top_k).

    Args:
        model_name: Tên model (vd: gpt-3.5-turbo, gemini-2.0-flash)
        reserve_tokens: Token dành riêng cho prompt/câu hỏi và phần trả lời

    Returns:
        max_tokens_per_chunk (int)
    """
    context_limits = {
        "gemini-2.0-flash": 24000,
        "gemini-2.5-flash": 24000,
    }

    max_context = context_limits.get(model_name, 8192)
    tokens_per_chunk = (max_context - reserve_tokens) // settings.TOP_K
    print(f"[INFO] Tokens per chunk: {tokens_per_chunk}")
    return max(500, tokens_per_chunk)


def count_tokens(text: str, tokenizer) -> int:
    return len(tokenizer.encode(text))


def chunk_text(
    text: str,
    model_name: str = "gpt-3.5-turbo",
    top_k: int = 3,
    overlap: int = 50,
    max_tokens: int = None,
) -> List[str]:
    """
    Chia nhỏ văn bản thành các đoạn (chunk) với giới hạn số token phù hợp cho RAG.

    Args:
        text (str): Nội dung văn bản đã xử lý sạch.
        model_name (str): Tên model đang dùng.
        top_k (int): Số chunk định lấy khi search RAG.
        overlap (int): Số token lặp lại giữa các đoạn để giữ ngữ cảnh.
        max_tokens (int): Nếu không cung cấp, tính tự động theo model_name.

    Returns:
        List[str]: Danh sách các chunk.
    """
    tokenizer = get_tokenizer(model_name)

    if max_tokens is None:
        # FIX: truyền reserve_tokens đúng tham số, không truyền top_k vào đây
        max_tokens = estimate_max_tokens_per_chunk(model_name)

    overlap = min(overlap, max_tokens - 1)

    tokens = tokenizer.encode(text)
    total_tokens = len(tokens)

    if total_tokens <= max_tokens:
        return [text.strip()]

    result_chunks = []  # FIX: đổi tên biến từ `chunks` → `result_chunks` tránh trùng tên hàm
    start = 0

    while start < total_tokens:
        end = min(start + max_tokens, total_tokens)
        chunk_tokens = tokens[start:end]
        chunk_str = tokenizer.decode(chunk_tokens).strip()  # FIX: đổi tên biến từ `chunk_text` → `chunk_str`
        result_chunks.append(chunk_str)

        start = max(0, end - overlap)

        if end == total_tokens:
            break

    return result_chunks