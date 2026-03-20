"""
Chat router — RAG + Gemini streaming + ảnh từ PDF + ảnh minh họa.
"""
import json
import logging

import google.generativeai as genai
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import AsyncGenerator

from app.core.config import settings
from app.models.database import get_db, ChatMessage, Session
from app.rag.retriever import Retriever
from qdrant_client import QdrantClient, AsyncQdrantClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

_kw = {"url": settings.QDRANT_URL, "api_key": settings.QDRANT_API_KEY}
_sync  = QdrantClient(**_kw, prefer_grpc=False)
_async = AsyncQdrantClient(**_kw, prefer_grpc=False)
_retriever = Retriever(client=_sync, async_client=_async)

genai.configure(api_key=settings.GEMINI_API_KEY)

SYSTEM_INSTRUCTION = """Bạn là **StudyBot** — trợ lý nghiên cứu khoa học AI cho sinh viên đại học Việt Nam.

## Nguồn thông tin
- Ưu tiên thông tin từ [CONTEXT] được cung cấp, trích dẫn: "Theo tài liệu **[tên file]**..."
- Nếu context không đủ, bổ sung kiến thức chung và ghi rõ "Bổ sung từ kiến thức chung:".

## Hình ảnh minh họa (QUAN TRỌNG)
Có 2 nguồn ảnh, ưu tiên theo thứ tự:

### Ưu tiên 1 — Ảnh từ tài liệu đã upload (nếu có)
Nếu trong [CONTEXT] có dòng `[HÌNH ẢNH: /images/xxx.jpg] mô tả...`
→ Chèn ảnh đó vào câu trả lời: `![Mô tả ảnh](http://localhost:8000/images/xxx.jpg)`
→ Đây là ảnh thật từ tài liệu của người dùng, ưu tiên dùng trước.

### Ưu tiên 2 — Ảnh minh họa từ internet (khi không có ảnh từ tài liệu)
Khi giải thích khái niệm trừu tượng, quy trình, hoặc người dùng yêu cầu xem ảnh/minh họa:
→ Dùng URL Unsplash thật theo format: `![Mô tả](https://images.unsplash.com/photo-ID?w=800&q=80)`
→ Chọn URL phù hợp nhất với nội dung từ danh sách:

Khoa học/Nghiên cứu: https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=800&q=80
AI/Machine Learning: https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=800&q=80
Lập trình/Code: https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=800&q=80
Toán học: https://images.unsplash.com/photo-1635070041078-e363dbe005cb?w=800&q=80
Sinh viên học tập: https://images.unsplash.com/photo-1523050854058-8df90110c9f1?w=800&q=80
Thư viện/Sách: https://images.unsplash.com/photo-1481627834876-b7833e8f5570?w=800&q=80
Dữ liệu/Biểu đồ: https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=800&q=80
Mạng nơ-ron/Deep learning: https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=800&q=80
Robot/Tự động hóa: https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=800&q=80
Bóng đá: https://images.unsplash.com/photo-1579952363873-27f3bade9f55?w=800&q=80
Thiên nhiên: https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=800&q=80
Thành phố: https://images.unsplash.com/photo-1477959858617-67f85cf4f1df?w=800&q=80

→ Nếu không có URL phù hợp, chọn gần nhất về chủ đề.
→ Chèn 1-2 ảnh, không chèn quá nhiều.

## Định dạng & độ dài
- Trả lời **ngắn gọn, súc tích** — tối đa 3-5 câu cho câu hỏi đơn giản.
- Chỉ dùng bullet list khi có từ 3 ý trở lên.
- KHÔNG viết lời mở đầu thừa như "Chào bạn!", "Cảm ơn câu hỏi hay!", "Tất nhiên rồi!".
- KHÔNG tóm tắt lại câu hỏi của người dùng.
- KHÔNG kết thúc bằng câu hỏi gợi ý trừ khi thật sự cần thiết.
- Nếu câu hỏi đơn giản → trả lời thẳng, 1-2 câu là đủ.
- Nếu cần giải thích dài → dùng heading và list để dễ đọc.

## Ngôn ngữ
Trả lời tiếng Việt. Thuật ngữ chuyên môn giữ tiếng Anh kèm giải thích lần đầu.
"""


class ChatRequest(BaseModel):
    session_id: str
    question: str


async def _stream(
    session_id: str,
    question: str,
    history: list[dict],
    db: AsyncSession,
) -> AsyncGenerator[str, None]:

    # ── 1. RAG retrieve ───────────────────────────────────
    try:
        chunks = await _retriever.retrieve_v3(question, bot_id=0)
        if not isinstance(chunks, list):
            chunks = list(chunks)
    except Exception as e:
        logger.error(f"Qdrant error: {e}")
        chunks = []

    source_names   = list({c.payload.get("doc_name", "") for c in chunks if c.payload})
    all_image_urls = []

    # ── 2. Build prompt với context + ảnh từ PDF ─────────
    ctx_parts = []
    for i, c in enumerate(chunks, 1):
        payload    = c.payload or {}
        content    = payload.get("content", "")
        doc_name   = payload.get("doc_name", "")
        updated    = payload.get("created_at", "")
        image_urls = payload.get("image_urls", [])
        img_descs  = payload.get("image_descs", [])

        all_image_urls.extend(image_urls)

        ctx_text = f"[CONTEXT {i}] Nguồn: {doc_name} | Cập nhật: {updated}\n{content}"

        # Thông báo cho Gemini biết có ảnh kèm theo chunk này
        if image_urls:
            img_lines = []
            for url, desc in zip(image_urls, img_descs or [""] * len(image_urls)):
                img_lines.append(f"[HÌNH ẢNH: {url}] {desc}")
            ctx_text += "\n" + "\n".join(img_lines)

        ctx_parts.append(ctx_text)

    if ctx_parts:
        src_str = ", ".join(f"**{n}**" for n in source_names if n)
        prompt  = f"Tài liệu tham khảo: {src_str}\n\n{'---'.join(ctx_parts)}\n\nCâu hỏi: {question}"
    else:
        prompt = question

    # ── 3. Lưu user message ───────────────────────────────
    db.add(ChatMessage(session_id=session_id, role="user", content=question))
    await db.commit()

    # ── 4. Gửi metadata về client ────────────────────────
    if source_names:
        yield f"data: [SOURCES]{json.dumps(source_names, ensure_ascii=False)}\n\n"

    if all_image_urls:
        unique_urls = list(dict.fromkeys(all_image_urls))
        yield f"data: [IMAGES]{json.dumps(unique_urls, ensure_ascii=False)}\n\n"

    # ── 5. Stream Gemini ──────────────────────────────────
    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        system_instruction=SYSTEM_INSTRUCTION,
        generation_config=genai.GenerationConfig(
            temperature=settings.TEMPERATURE,
            max_output_tokens=settings.MAX_OUTPUT_TOKENS,
        ),
    )
    chat_s = model.start_chat(history=[
        {"role": m["role"], "parts": [{"text": m["content"]}]}
        for m in history[-20:]
    ])

    full = ""
    try:
        stream = await chat_s.send_message_async(prompt, stream=True)
        async for chunk in stream:
            if chunk.text:
                full += chunk.text
                yield f"data: {chunk.text.replace(chr(10), chr(92)+'n')}\n\n"
    except Exception as e:
        err = str(e)
        msg = "Hệ thống quá tải, thử lại sau." if "429" in err or "quota" in err.lower() else f"Lỗi: {err[:80]}"
        yield f"data: {msg}\n\n"

    # ── 6. Lưu bot message ────────────────────────────────
    if full:
        db.add(ChatMessage(
            session_id=session_id, role="model", content=full,
            source_docs="|".join(source_names) if source_names else None,
        ))
        res = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id, ChatMessage.role == "user")
        )
        if len(res.scalars().all()) == 1:
            title = question[:60] + ("..." if len(question) > 60 else "")
            await db.execute(
                update(Session).where(Session.id == session_id).values(title=title)
            )
        await db.commit()

    yield "data: [DONE]\n\n"


@router.post("/stream")
async def chat_stream(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    if not req.question.strip():
        raise HTTPException(400, "Câu hỏi không được rỗng")
    res = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == req.session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    history = [{"role": m.role, "content": m.content} for m in res.scalars().all()]
    return StreamingResponse(
        _stream(req.session_id, req.question, history, db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )