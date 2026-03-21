"""
Chat router — RAG + Gemini streaming + hỗ trợ ảnh người dùng upload.
- Không hiểu nhầm "tiếng Anh" thành "ảnh"
- Chỉ hiện ảnh khi user có ý định xem trực quan
- Lọc ảnh theo semantic similarity giữa câu hỏi và nội dung ảnh/chunk
"""
import json
import logging
import math
import re
import unicodedata
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
from app.rag.embedder import get_embeddings
from app.rag.retriever import Retriever

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


def _parse_meta(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"sources": [s for s in raw.split("|") if s]}


def _normalize_text(text: str) -> str:
    text = (text or "").lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _wants_visual(question: str) -> bool:
    """
    Chỉ nhận diện ý định muốn xem trực quan.
    Không bắt keyword đơn lẻ 'anh' để tránh nhầm với 'tiếng Anh'.
    """
    q = _normalize_text(question)
    phrases = [
        "xem anh",
        "xem hinh",
        "cho xem anh",
        "cho xem hinh",
        "in ra bang",
        "hien thi bang",
        "xem bang",
        "mo bang",
        "hien thi anh",
        "hien thi hinh",
        "xem hinh minh hoa",
        "in ra hinh",
        "picture",
        "image",
        "photo",
    ]
    return any(p in q for p in phrases)


def _is_image_followup(question: str) -> bool:
    """
    Chỉ dùng cho luồng hỏi tiếp về ảnh đã upload.
    Không dùng từ đơn 'anh'.
    """
    q = _normalize_text(question)
    phrases = [
        "xem anh",
        "xem hinh",
        "trong anh",
        "trong hinh",
        "anh nay",
        "hinh nay",
        "buc anh",
        "buc hinh",
        "tam anh",
        "tam hinh",
        "picture",
        "image",
        "photo",
    ]
    return any(p in q for p in phrases)


def _is_text_focused_image_request(question: str) -> bool:
    q = question.lower()
    keywords = [
        "tóm tắt", "tom tat",
        "nội dung", "noi dung",
        "văn bản", "van ban",
        "chữ", "chu",
        "đọc", "doc",
        "ocr",
        "dịch", "dich",
        "ghi gì", "viet gi", "text",
        "trích", "trich",
        "ý chính", "y chinh",
        "main idea",
        "nói gì", "noi gi",
        "bài viết", "bai viet",
    ]
    return any(k in q for k in keywords)


def _to_list(x):
    if x is None:
        return None
    if hasattr(x, "tolist"):
        return x.tolist()
    return x


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def _collect_relevant_images_semantic(question: str, chunks: list, limit: int = 2) -> list[str]:
    """
    Chỉ lấy ảnh nếu:
    1) user có ý định xem trực quan
    2) ảnh/chunk đủ liên quan ngữ nghĩa với câu hỏi
    """
    if not _wants_visual(question):
        return []

    try:
        q_dense, _, _ = get_embeddings([question])
        if q_dense is None or len(q_dense) == 0:
            return []
        q_vec = _to_list(q_dense[0])
        if not q_vec:
            return []
    except Exception as e:
        logger.warning("Image semantic filter embedding failed: %s", e)
        return []

    candidates: list[tuple[float, str]] = []
    seen = set()

    for c in chunks:
        payload = c.payload or {}
        image_urls = payload.get("image_urls", []) or []
        if not image_urls:
            continue

        rep_text_parts = []
        rep_text_parts.extend(payload.get("image_descs", []) or [])
        rep_text_parts.append(payload.get("content", "") or "")
        rep_text_parts.append(payload.get("doc_name", "") or "")
        rep_text = "\n".join([x for x in rep_text_parts if x]).strip()

        if not rep_text:
            continue

        try:
            d_dense, _, _ = get_embeddings([rep_text])
            if d_dense is None or len(d_dense) == 0:
                continue
            d_vec = _to_list(d_dense[0])
            score = _cosine_similarity(q_vec, d_vec)
        except Exception as e:
            logger.warning("Image candidate embedding failed: %s", e)
            score = 0.0

        for url in image_urls:
            if url and url not in seen:
                seen.add(url)
                candidates.append((score, url))

    candidates.sort(key=lambda x: x[0], reverse=True)

    threshold = 0.45
    selected = [url for score, url in candidates if score >= threshold][:limit]

    logger.info("Selected %s relevant images for question='%s'", len(selected), question)
    return selected


def _build_upload_image_prompt(user_prompt: str) -> str:
    if _is_text_focused_image_request(user_prompt):
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
    if _is_text_focused_image_request(question):
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


async def _maybe_set_title(db: AsyncSession, session_id: str, title_seed: str):
    res = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.role == "user")
    )
    user_msgs = res.scalars().all()
    if len(user_msgs) == 1:
        title = title_seed[:60] + ("..." if len(title_seed) > 60 else "")
        await db.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(title=title)
        )
        await db.commit()


async def _find_last_uploaded_image(session_id: str, db: AsyncSession) -> str | None:
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


def _open_local_image_from_url(image_url: str) -> Image.Image:
    rel = image_url.replace("/images/", "", 1).lstrip("/")
    path = BASE_DIR / "data" / "images" / rel
    return Image.open(path).convert("RGB")


async def _vision_answer_for_uploaded_image(*, question: str, image_url: str) -> str:
    img = _open_local_image_from_url(image_url)

    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        system_instruction=SYSTEM_INSTRUCTION,
        generation_config=genai.GenerationConfig(
            temperature=settings.TEMPERATURE,
            max_output_tokens=settings.MAX_OUTPUT_TOKENS,
        ),
    )

    prompt = _build_followup_image_prompt(question)
    res = await model.generate_content_async([prompt, img])
    text = getattr(res, "text", "") or "Mình chưa phân tích được ảnh này."
    return text.strip()


async def _stream_text_answer(
    *,
    session_id: str,
    question: str,
    history: list[dict],
) -> AsyncGenerator[str, None]:
    async with AsyncSessionLocal() as db:
        try:
            try:
                chunks = await _retriever.retrieve_v3(question, bot_id=0)
                if not isinstance(chunks, list):
                    chunks = list(chunks)
            except Exception as e:
                logger.error("Qdrant error: %s", e)
                chunks = []

            source_names = list({
                c.payload.get("doc_name", "")
                for c in chunks
                if c.payload and c.payload.get("doc_name")
            })

            ctx_parts = []
            for i, c in enumerate(chunks, 1):
                payload = c.payload or {}
                content = payload.get("content", "")
                doc_name = payload.get("doc_name", "")
                updated = payload.get("created_at", "")
                image_urls = payload.get("image_urls", []) or []
                img_descs = payload.get("image_descs", []) or []

                ctx_text = f"[CONTEXT {i}] Nguồn: {doc_name} | Cập nhật: {updated}\n{content}"

                if image_urls:
                    img_lines = []
                    for idx, url in enumerate(image_urls):
                        desc = img_descs[idx] if idx < len(img_descs) else ""
                        img_lines.append(f"[HÌNH ẢNH: {url}] {desc}".strip())
                    ctx_text += "\n" + "\n".join(img_lines)

                ctx_parts.append(ctx_text)

            if ctx_parts:
                src_str = ", ".join(f"**{n}**" for n in source_names if n)
                prompt = (
                    f"Tài liệu tham khảo: {src_str}\n\n"
                    f"{'---'.join(ctx_parts)}\n\n"
                    f"Câu hỏi: {question}"
                )
            else:
                prompt = question

            db.add(ChatMessage(session_id=session_id, role="user", content=question))
            await db.commit()

            if source_names:
                yield f"data: [SOURCES]{json.dumps(source_names, ensure_ascii=False)}\n\n"

            selected_images = await _collect_relevant_images_semantic(question, chunks, limit=2)
            if selected_images:
                yield f"data: [IMAGES]{json.dumps(selected_images, ensure_ascii=False)}\n\n"

            model = genai.GenerativeModel(
                model_name=settings.GEMINI_MODEL,
                system_instruction=SYSTEM_INSTRUCTION,
                generation_config=genai.GenerationConfig(
                    temperature=settings.TEMPERATURE,
                    max_output_tokens=settings.MAX_OUTPUT_TOKENS,
                ),
            )

            chat_s = model.start_chat(
                history=[
                    {"role": m["role"], "parts": [{"text": m["content"]}]}
                    for m in history[-20:]
                ]
            )

            full = ""
            try:
                stream = await chat_s.send_message_async(prompt, stream=True)
                async for chunk in stream:
                    delta = getattr(chunk, "text", "") or ""
                    if delta:
                        full += delta
                        yield f"data: {delta.replace(chr(10), chr(92) + 'n')}\n\n"
            except Exception as e:
                err = str(e)
                msg = "Hệ thống quá tải, thử lại sau." if "429" in err or "quota" in err.lower() else f"Lỗi: {err[:120]}"
                yield f"data: {msg}\n\n"
                full = msg

            db.add(ChatMessage(
                session_id=session_id,
                role="model",
                content=full,
                source_docs=_pack_meta(sources=source_names, images=selected_images, kind="rag"),
            ))
            await db.commit()
            await _maybe_set_title(db, session_id, question)

            yield "data: [DONE]\n\n"
        finally:
            await db.close()


async def _stream_followup_about_last_image(
    *,
    session_id: str,
    question: str,
) -> AsyncGenerator[str, None]:
    async with AsyncSessionLocal() as db:
        try:
            image_url = await _find_last_uploaded_image(session_id, db)
            if not image_url:
                yield "data: Mình chưa thấy ảnh nào được gửi trong phiên chat này.\n\n"
                yield "data: [DONE]\n\n"
                return

            db.add(ChatMessage(session_id=session_id, role="user", content=question))
            await db.commit()

            yield f"data: [IMAGES]{json.dumps([image_url], ensure_ascii=False)}\n\n"

            try:
                full = await _vision_answer_for_uploaded_image(question=question, image_url=image_url)
            except Exception as e:
                logger.exception("Vision follow-up error: %s", e)
                full = "Mình chưa phân tích tiếp được ảnh này. Hãy thử lại."

            yield f"data: {full.replace(chr(10), chr(92) + 'n')}\n\n"

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

    if _is_image_followup(req.question):
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

        prompt = _build_upload_image_prompt(user_prompt)
        res = await model.generate_content_async([prompt, pil_img])
        answer = (getattr(res, "text", "") or "").strip() or "Mình chưa phân tích được ảnh này."
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