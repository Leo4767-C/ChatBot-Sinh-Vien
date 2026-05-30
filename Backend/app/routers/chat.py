"""
chat.py — RAG + Gemini streaming + hỗ trợ ảnh người dùng upload.

FIXES:
  1. history không còn bị cắt cứng 20 tin nhắn — thay vào đó cắt theo token budget
  2. prompt gửi Gemini chỉ dùng effective_question (đã rewrite), KHÔNG gửi câu gốc song song
  3. history truyền vào _rewrite_followup_question lấy từ DB trước khi lưu tin hiện tại
     → _last_meaningful_model_answer() luôn trả đúng câu trả lời bot gần nhất
  4. System prompt hợp nhất, không nhân đôi
  5. Nếu retrieve trúng chunk bảng (is_table=True) thì ưu tiên ép model trả bảng Markdown
"""
import json
import logging
import uuid
from io import BytesIO
from pathlib import Path
from typing import AsyncGenerator

import google.generativeai as genai
from PIL import Image
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient, QdrantClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.database import AsyncSessionLocal, ChatMessage, Session, get_db
from app.rag.retriever import Retriever

# ─── Import từ các module đã tách ────────────────────────────────────────────
from app.routers.chat_formatters import (
    normalize_text,
    wants_table_answer,
    postprocess_answer,
)
from app.routers.chat_followup import (
    is_reference_followup,
    last_meaningful_model_answer,
    extract_referenced_item,
    rewrite_followup_question,
    trim_history_by_token_budget,
    HISTORY_TOKEN_BUDGET,
)
from app.routers.chat_vision import (
    is_image_followup,
    is_text_focused_image_request,
    build_upload_image_prompt,
    find_last_uploaded_image,
    open_local_image_from_url,
    vision_answer_for_uploaded_image,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

_kw = {"url": settings.QDRANT_URL, "api_key": settings.QDRANT_API_KEY}
_sync = QdrantClient(**_kw, prefer_grpc=False)
_async = AsyncQdrantClient(**_kw, prefer_grpc=False)
_retriever = Retriever(client=_sync, async_client=_async)

genai.configure(api_key=settings.EFFECTIVE_GEMINI_API_KEY)

BASE_DIR = Path(__file__).resolve().parents[1]
UPLOAD_DIR = BASE_DIR / "data" / "images" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_INSTRUCTION = """Bạn là StudyBot — trợ lý nghiên cứu khoa học AI cho sinh viên đại học Việt Nam.

Quy tắc:
- Ưu tiên thông tin từ [CONTEXT] nếu có.
- Nếu ngữ cảnh có bảng hoặc dữ liệu ngắn, rõ cột, dễ đối chiếu, hãy ưu tiên bảng Markdown.
- Nếu nội dung dài, nhiều điều kiện, nhiều giải thích, hãy dùng bullet list.
- Không nhét cả đoạn văn dài vào một ô của bảng.
- Không bao giờ in ra đường dẫn ảnh, tên file ảnh, hoặc URL nội bộ như /images/...
- Nếu người dùng gửi ảnh tài liệu hoặc ảnh có chữ:
  - ưu tiên đọc phần chữ và nội dung văn bản
  - nếu người dùng yêu cầu tóm tắt, hãy tóm tắt nội dung chính
  - không mô tả khung cảnh, màu sắc, con người nếu điều đó không cần thiết
- Nếu người dùng hỏi mô tả ảnh, mới mô tả những gì nhìn thấy trong ảnh.
- Không bịa chi tiết không nhìn rõ.
- Trả lời bằng tiếng Việt, ngắn gọn, rõ ràng.
"""


class ChatRequest(BaseModel):
    session_id: str
    question: str


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _pack_meta(
    *,
    sources: list[str] | None = None,
    images: list[str] | None = None,
    kind: str | None = None,
) -> str | None:
    data: dict = {}
    if sources:
        data["sources"] = sources
    if images:
        data["images"] = images
    if kind:
        data["kind"] = kind
    return json.dumps(data, ensure_ascii=False) if data else None


def _is_reference_source_name(name: str) -> bool:
    source_name = (name or "").strip().lower()
    if not source_name:
        return False
    return Path(source_name).suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _safe_chunk_text(chunk) -> str:
    try:
        candidates = getattr(chunk, "candidates", None) or []
        texts: list[str] = []
        for cand in candidates:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                txt = getattr(part, "text", None)
                if txt:
                    texts.append(txt)
        if texts:
            return "".join(texts)
        txt = getattr(chunk, "text", None)
        return txt or ""
    except Exception:
        return ""


async def _maybe_set_title(db: AsyncSession, session_id: str, title_seed: str):
    res = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.role == "user")
    )
    user_msgs = res.scalars().all()
    if len(user_msgs) == 1:
        title = title_seed[:60] + ("..." if len(title_seed) > 60 else "")
        await db.execute(
            update(Session).where(Session.id == session_id).values(title=title)
        )
        await db.commit()


# ─── RAG Streaming ───────────────────────────────────────────────────────────

async def _stream_text_answer(
    *,
    session_id: str,
    question: str,
    history: list[dict],
) -> AsyncGenerator[str, None]:
    async with AsyncSessionLocal() as db:
        try:
            effective_question = rewrite_followup_question(question, history)

            is_self_contained_followup = (
                is_reference_followup(question)
                and effective_question != question
                and extract_referenced_item(question, last_meaningful_model_answer(history)) != ""
            )

            if is_self_contained_followup:
                chunks = []
                source_names = []
                ctx_parts = []
                has_table_context = False
                logger.info("Follow-up self-contained — skipping RAG retrieval")
            else:
                try:
                    chunks = await _retriever.retrieve_v3(effective_question, bot_id=0)
                    if not isinstance(chunks, list):
                        chunks = list(chunks)
                except Exception as e:
                    logger.error("Qdrant error: %s", e)
                    chunks = []

                source_names = list({
                    c.payload.get("doc_name", "")
                    for c in chunks
                    if c.payload
                    and c.payload.get("doc_name")
                    and _is_reference_source_name(c.payload.get("doc_name", ""))
                })

                has_table_context = any(
                    bool((c.payload or {}).get("is_table", False))
                    for c in chunks
                )

                ctx_parts = []
                for i, c in enumerate(chunks, 1):
                    payload = c.payload or {}
                    content = payload.get("content", "")
                    doc_name = payload.get("doc_name", "")
                    updated = payload.get("created_at", "")
                    img_descs = payload.get("image_descs", []) or []
                    is_table = bool(payload.get("is_table", False))

                    label = "BẢNG" if is_table else "CONTEXT"
                    ctx_text = f"[{label} {i}] Nguồn: {doc_name} | Cập nhật: {updated}\n{content}"

                    if img_descs:
                        desc_lines = [f"[HÌNH ẢNH] {desc}" for desc in img_descs if desc]
                        if desc_lines:
                            ctx_text += "\n" + "\n".join(desc_lines)

                    ctx_parts.append(ctx_text)

            if ctx_parts:
                src_str = ", ".join(f"**{n}**" for n in source_names if n)

                if has_table_context or wants_table_answer(effective_question):
                    extra_instruction = (
                        "\n\nYÊU CẦU ĐỊNH DẠNG:\n"
                        "- Nếu trong ngữ cảnh có bảng, hãy ưu tiên giữ nguyên thông tin dưới dạng bảng Markdown chuẩn.\n"
                        "- Nếu dữ liệu ngắn, đồng đều, dễ đối chiếu, hãy ưu tiên bảng Markdown.\n"
                        "- Nếu số ý ít và mỗi ý ngắn, có thể trình bày thành bảng 2 hoặc 3 cột.\n"
                        "- Không gộp cả đoạn văn dài vào một ô.\n"
                        "- Nếu có cột STT thì giữ cột STT.\n"
                        "- Nếu bảng trong ngữ cảnh đã rõ cột/hàng, hãy bám sát cấu trúc đó để trả lời.\n"
                        "- Chỉ khi nội dung quá dài, ô quá dài hoặc bảng bị vỡ thì mới chuyển sang bullet list.\n"
                        "- Không in đường dẫn ảnh, tên file ảnh hoặc URL nội bộ.\n"
                    )
                else:
                    extra_instruction = (
                        "\n\nYÊU CẦU ĐỊNH DẠNG:\n"
                        "- Ưu tiên bullet list ngắn gọn, dễ đọc.\n"
                        "- Nếu các ý ngắn, đồng đều, dưới 10 dòng và dễ đối chiếu thì có thể dùng bảng Markdown.\n"
                    )

                prompt = (
                    f"Tài liệu tham khảo: {src_str}\n\n"
                    f"{'---'.join(ctx_parts)}\n\n"
                    f"Câu hỏi: {effective_question}"
                    f"{extra_instruction}"
                )
            else:
                prompt = effective_question

            db.add(ChatMessage(session_id=session_id, role="user", content=question))
            await db.commit()

            if source_names:
                yield f"data: [SOURCES]{json.dumps(source_names, ensure_ascii=False)}\n\n"

            model = genai.GenerativeModel(
                model_name=settings.GEMINI_MODEL,
                system_instruction=SYSTEM_INSTRUCTION,
                generation_config=genai.GenerationConfig(
                    temperature=settings.TEMPERATURE,
                    max_output_tokens=settings.MAX_OUTPUT_TOKENS,
                ),
            )

            trimmed_history = trim_history_by_token_budget(history, HISTORY_TOKEN_BUDGET)

            chat_s = model.start_chat(
                history=[
                    {"role": m["role"], "parts": [{"text": m["content"]}]}
                    for m in trimmed_history
                ]
            )

            full = ""
            try:
                stream = await chat_s.send_message_async(prompt, stream=True)
                async for chunk in stream:
                    delta = _safe_chunk_text(chunk)
                    if delta:
                        full += delta
                        yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
            except Exception as e:
                err = str(e)
                msg = (
                    "Hệ thống quá tải, thử lại sau."
                    if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err
                    else f"Lỗi: {err[:160]}"
                )
                logger.exception("Gemini stream error: %s", err)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                full = msg

            full = postprocess_answer(full, effective_question)

            db.add(ChatMessage(
                session_id=session_id,
                role="model",
                content=full,
                source_docs=_pack_meta(sources=source_names, kind="rag"),
            ))
            await db.commit()
            await _maybe_set_title(db, session_id, question)

            yield "data: [DONE]\n\n"
        finally:
            await db.close()


# ─── Vision Follow-up Streaming ──────────────────────────────────────────────

async def _stream_followup_about_last_image(
    *,
    session_id: str,
    question: str,
) -> AsyncGenerator[str, None]:
    async with AsyncSessionLocal() as db:
        try:
            image_url = await find_last_uploaded_image(session_id, db)
            if not image_url:
                yield "data: Mình chưa thấy ảnh nào được gửi trong phiên chat này.\n\n"
                yield "data: [DONE]\n\n"
                return

            db.add(ChatMessage(session_id=session_id, role="user", content=question))
            await db.commit()

            yield f"data: [IMAGES]{json.dumps([image_url], ensure_ascii=False)}\n\n"

            try:
                full = await vision_answer_for_uploaded_image(
                    question=question,
                    image_url=image_url,
                    system_instruction=SYSTEM_INSTRUCTION,
                )
            except Exception as e:
                logger.exception("Vision follow-up error: %s", e)
                full = "Mình chưa phân tích tiếp được ảnh này. Hãy thử lại."

            yield f"data: {json.dumps(full, ensure_ascii=False)}\n\n"

            db.add(ChatMessage(
                session_id=session_id,
                role="model",
                content=full,
                source_docs=_pack_meta(images=[image_url], kind="vision_followup"),
            ))
            await db.commit()
            await _maybe_set_title(db, session_id, question)

            yield "data: [DONE]\n\n"
        finally:
            await db.close()


# ─── API Endpoints ───────────────────────────────────────────────────────────

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

    await db.close()

    if is_image_followup(req.question):
        stream = _stream_followup_about_last_image(
            session_id=req.session_id,
            question=req.question,
        )
    else:
        stream = _stream_text_answer(
            session_id=req.session_id,
            question=req.question,
            history=history,
        )

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/image")
async def analyze_uploaded_image(
    session_id: str = Form(...),
    question: str = Form(""),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if image.content_type not in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
        raise HTTPException(400, "Chỉ hỗ trợ PNG, JPG, JPEG, WEBP")

    raw = await image.read()
    if not raw:
        raise HTTPException(400, "Ảnh rỗng")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(400, "Ảnh vượt quá 5MB")

    ext = Path(image.filename or "upload.jpg").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".jpg"

    filename = f"{uuid.uuid4().hex}{ext}"
    save_path = UPLOAD_DIR / filename
    save_path.write_bytes(raw)

    image_url = f"/images/uploads/{filename}"
    user_prompt = question.strip() or "Hãy đọc và tóm tắt nội dung trong ảnh này."

    db.add(ChatMessage(
        session_id=session_id,
        role="user",
        content=user_prompt,
        source_docs=_pack_meta(images=[image_url], kind="user_image"),
    ))
    await db.commit()

    try:
        pil_img = Image.open(BytesIO(raw)).convert("RGB")
        model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            system_instruction=SYSTEM_INSTRUCTION,
            generation_config=genai.GenerationConfig(
                temperature=settings.TEMPERATURE,
                max_output_tokens=settings.MAX_OUTPUT_TOKENS,
            ),
        )
        prompt = build_upload_image_prompt(user_prompt)
        res = await model.generate_content_async([prompt, pil_img])

        try:
            answer = (getattr(res, "text", None) or "").strip()
        except Exception:
            answer = ""

        if not answer:
            candidates = getattr(res, "candidates", None) or []
            texts: list[str] = []
            for cand in candidates:
                content = getattr(cand, "content", None)
                parts = getattr(content, "parts", None) or []
                for part in parts:
                    txt = getattr(part, "text", None)
                    if txt:
                        texts.append(txt)
            answer = "".join(texts).strip()

        answer = answer or "Mình chưa phân tích được ảnh này."
        answer = postprocess_answer(answer, user_prompt)
    except Exception as e:
        logger.exception("Analyze uploaded image error: %s", e)
        answer = "Mình chưa phân tích được ảnh này. Hãy thử lại."

    db.add(ChatMessage(
        session_id=session_id,
        role="model",
        content=answer,
        source_docs=_pack_meta(images=[image_url], kind="vision_upload"),
    ))
    await db.commit()
    await _maybe_set_title(db, session_id, user_prompt)

    return {
        "ok": True,
        "answer": answer,
        "image_url": image_url,
    }
