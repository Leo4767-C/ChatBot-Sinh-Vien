"""
chat_vision.py — Xử lý ảnh người dùng upload: build prompt, gọi Gemini Vision,
tìm ảnh đã gửi trước đó trong session.
"""
import logging
from pathlib import Path

import google.generativeai as genai
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.database import ChatMessage
from app.routers.chat_formatters import normalize_text, postprocess_answer

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]


def is_image_followup(question: str) -> bool:
    q = normalize_text(question)
    phrases = [
        "xem anh", "xem hinh", "trong anh", "trong hinh",
        "anh nay", "hinh nay", "buc anh", "buc hinh",
        "tam anh", "tam hinh", "picture", "image", "photo",
    ]
    return any(p in q for p in phrases)


def is_text_focused_image_request(question: str) -> bool:
    q = question.lower()
    keywords = [
        "tóm tắt", "tom tat", "nội dung", "noi dung",
        "văn bản", "van ban", "chữ", "chu", "đọc", "doc",
        "ocr", "dịch", "dich", "ghi gì", "viet gi", "text",
        "trích", "trich", "ý chính", "y chinh", "main idea",
        "nói gì", "noi gi", "bài viết", "bai viet",
    ]
    return any(k in q for k in keywords)


def build_upload_image_prompt(user_prompt: str) -> str:
    if is_text_focused_image_request(user_prompt):
        return (
            f"Câu hỏi của người dùng: {user_prompt}\n\n"
            "Ưu tiên xử lý PHẦN CHỮ hoặc NỘI DUNG VĂN BẢN trong ảnh.\n"
            "Hãy đọc nội dung nhìn thấy rõ, rồi trả lời đúng yêu cầu của người dùng.\n"
            "Nếu người dùng yêu cầu tóm tắt, chỉ tóm tắt nội dung chính của văn bản trong ảnh.\n"
            "KHÔNG mô tả bố cục, con người, màu sắc, hay khung cảnh trong ảnh trừ khi thật sự cần để hiểu văn bản.\n"
            "Nếu chữ mờ hoặc không đọc được hết, nói rõ phần nào không nhìn đủ rõ."
        )
    return (
        f"Câu hỏi của người dùng: {user_prompt}\n\n"
        "Hãy mô tả ảnh bằng tiếng Việt, ngắn gọn nhưng đủ ý.\n"
        "Nếu ảnh có chữ, đọc lại phần chữ thấy rõ.\n"
        "Nếu có chi tiết không rõ, nói rõ là không nhìn đủ rõ."
    )


def _build_followup_image_prompt(question: str) -> str:
    if is_text_focused_image_request(question):
        return (
            "Người dùng đang hỏi về ảnh đã gửi trong cuộc trò chuyện.\n"
            f"Câu hỏi: {question}\n\n"
            "Ưu tiên phần chữ hoặc nội dung văn bản trong ảnh.\n"
            "Nếu người dùng yêu cầu tóm tắt, chỉ tóm tắt nội dung chính của văn bản.\n"
            "Không mô tả khung cảnh, màu sắc, con người hoặc bố cục nếu không cần.\n"
            "Nếu chữ không rõ, hãy nói rõ là không nhìn đủ rõ."
        )
    return (
        "Người dùng đang hỏi về ảnh đã gửi trong cuộc trò chuyện.\n"
        f"Câu hỏi: {question}\n\n"
        "Hãy trả lời ngắn gọn bằng tiếng Việt, chỉ dựa trên những gì thấy rõ trong ảnh.\n"
        "Nếu có chi tiết không chắc, nói rõ là không nhìn đủ rõ."
    )


def _parse_meta(raw: str | None) -> dict:
    import json
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"sources": [s for s in raw.split("|") if s]}


async def find_last_uploaded_image(session_id: str, db: AsyncSession) -> str | None:
    res = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
    )
    for msg in res.scalars().all():
        meta = _parse_meta(msg.source_docs)
        images = meta.get("images", [])
        kind = meta.get("kind")
        if kind == "user_image" and images:
            return images[0]
    return None


def open_local_image_from_url(image_url: str) -> Image.Image:
    rel = image_url.replace("/images/", "", 1).lstrip("/")
    path = BASE_DIR / "data" / "images" / rel
    return Image.open(path).convert("RGB")


async def vision_answer_for_uploaded_image(
    *,
    question: str,
    image_url: str,
    system_instruction: str,
) -> str:
    img = open_local_image_from_url(image_url)
    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        system_instruction=system_instruction,
        generation_config=genai.GenerationConfig(
            temperature=settings.TEMPERATURE,
            max_output_tokens=settings.MAX_OUTPUT_TOKENS,
        ),
    )
    prompt = _build_followup_image_prompt(question)
    res = await model.generate_content_async([prompt, img])
    try:
        text = getattr(res, "text", None) or ""
    except Exception:
        text = ""
        candidates = getattr(res, "candidates", None) or []
        for cand in candidates:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                txt = getattr(part, "text", None)
                if txt:
                    text += txt
    if not text:
        text = "Mình chưa phân tích được ảnh này."
    return postprocess_answer(text.strip(), question)
