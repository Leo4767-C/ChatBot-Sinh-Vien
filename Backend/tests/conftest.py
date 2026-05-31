"""
conftest.py — Shared fixtures for the entire test suite.

Cung cấp:
- sample history data cho chat tests
- temporary file fixtures cho RAG tests
- common test constants
"""
import os
import sys
from pathlib import Path

import pytest

# ─── Đảm bảo import path đúng ─────────────────────────────────────────────────
# Thêm Backend/ vào sys.path để `from app.xxx import yyy` hoạt động trong tests
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ─── Thiết lập biến môi trường trước khi import app modules ───────────────────
# Tránh lỗi do thiếu .env khi chạy test trên CI/CD
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real")
os.environ.setdefault("GOOGLE_API_KEY", "test-key-not-real")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_chat_history() -> list[dict]:
    """Lịch sử chat giả lập cho các test follow-up."""
    return [
        {"role": "user", "content": "Điểm chuẩn của các ngành CNTT là bao nhiêu?"},
        {
            "role": "model",
            "content": (
                "Dưới đây là điểm chuẩn các ngành CNTT năm 2024:\n\n"
                "1. Công nghệ thông tin: 26.5 điểm\n"
                "2. Khoa học máy tính: 27.0 điểm\n"
                "3. Kỹ thuật phần mềm: 25.8 điểm\n"
                "4. An toàn thông tin: 24.5 điểm\n"
                "5. Trí tuệ nhân tạo: 28.0 điểm"
            ),
        },
    ]


@pytest.fixture
def sample_model_answer_with_bullets() -> str:
    """Câu trả lời mẫu dạng bullet list."""
    return (
        "Các yêu cầu đầu vào:\n"
        "- Điểm trung bình: trên 7.0\n"
        "- Chứng chỉ tiếng Anh: IELTS 5.5\n"
        "- Thư giới thiệu: 2 bức từ giảng viên\n"
        "- CV cá nhân: đầy đủ thông tin học tập"
    )


@pytest.fixture
def sample_table_answer() -> str:
    """Câu trả lời mẫu dạng bảng Markdown."""
    return (
        "| Ngành | Điểm chuẩn | Chỉ tiêu |\n"
        "|---|---|---|\n"
        "| CNTT | 26.5 | 200 |\n"
        "| KHMT | 27.0 | 150 |\n"
        "| KTPM | 25.8 | 180 |"
    )


@pytest.fixture
def empty_history() -> list[dict]:
    """Lịch sử chat rỗng."""
    return []


@pytest.fixture
def long_history() -> list[dict]:
    """Lịch sử chat dài (để test token budget trimming)."""
    history = []
    for i in range(50):
        history.append({
            "role": "user",
            "content": f"Câu hỏi số {i + 1}: " + "nội dung " * 50,
        })
        history.append({
            "role": "model",
            "content": f"Câu trả lời số {i + 1}: " + "giải thích chi tiết " * 80,
        })
    return history


@pytest.fixture
def tmp_text_file(tmp_path) -> Path:
    """Tạo file text tạm thời cho test chunking."""
    file = tmp_path / "sample.txt"
    file.write_text(
        "Chương 1: Giới thiệu\n\n"
        "Đây là nội dung phần giới thiệu.\n\n"
        "Chương 2: Phương pháp nghiên cứu\n\n"
        "Nội dung phương pháp nghiên cứu được trình bày ở đây.\n"
        "Phương pháp bao gồm khảo sát, phân tích và tổng hợp dữ liệu.\n\n"
        "Chương 3: Kết quả\n\n"
        "Kết quả nghiên cứu cho thấy nhiều phát hiện quan trọng.\n",
        encoding="utf-8",
    )
    return file


@pytest.fixture
def tmp_markdown_file(tmp_path) -> Path:
    """Tạo file markdown tạm thời cho test chunking."""
    file = tmp_path / "document.md"
    file.write_text(
        "# Quy chế đào tạo\n\n"
        "## Điều 1: Phạm vi áp dụng\n\n"
        "Quy chế này áp dụng cho tất cả sinh viên đại học.\n\n"
        "## Điều 2: Đối tượng\n\n"
        "Đối tượng bao gồm sinh viên chính quy và vừa làm vừa học.\n\n"
        "### 2.1. Sinh viên chính quy\n\n"
        "Sinh viên theo học toàn thời gian tại trường.\n\n"
        "### 2.2. Sinh viên vừa làm vừa học\n\n"
        "Sinh viên theo học ngoài giờ hành chính.\n",
        encoding="utf-8",
    )
    return file
