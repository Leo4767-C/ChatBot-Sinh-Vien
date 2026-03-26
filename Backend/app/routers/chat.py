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

# ─── Token budget cho history ───────────────────────────────────────────────
# Gemini 2.5-flash có context 1M token, nhưng ta để 12k cho history là thừa sức
# đủ ~40-60 lượt hỏi đáp. Tăng con số này nếu cần.
HISTORY_TOKEN_BUDGET = 12_000

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


def _is_image_followup(question: str) -> bool:
    q = _normalize_text(question)
    phrases = [
        "xem anh", "xem hinh", "trong anh", "trong hinh",
        "anh nay", "hinh nay", "buc anh", "buc hinh",
        "tam anh", "tam hinh", "picture", "image", "photo",
    ]
    return any(p in q for p in phrases)


def _is_text_focused_image_request(question: str) -> bool:
    q = question.lower()
    keywords = [
        "tóm tắt", "tom tat", "nội dung", "noi dung",
        "văn bản", "van ban", "chữ", "chu", "đọc", "doc",
        "ocr", "dịch", "dich", "ghi gì", "viet gi", "text",
        "trích", "trich", "ý chính", "y chinh", "main idea",
        "nói gì", "noi gi", "bài viết", "bai viet",
    ]
    return any(k in q for k in keywords)


def _wants_table_answer(question: str) -> bool:
    q = _normalize_text(question)
    positive_phrases = [
        "diem chuan", "hoc phi", "chung chi", "tuong duong",
        "tham chieu", "muc diem", "thang diem", "quy doi",
        "xep loai", "danh sach", "bao gom", "gom nhung gi",
        "cac muc", "cac nhom", "cac bac", "cac to chuc",
        "cac co so", "doi chieu", "so sanh", "cac nganh",
        "khoa kinh te", "khoa cong nghe thong tin", "cntt",
        "bang", "in ra bang", "dang bang", "trinh bay dang bang",
    ]
    return any(p in q for p in positive_phrases)


def _strip_md_prefix(line: str) -> str:
    line = (line or "").strip()
    line = re.sub(r"^\s*[-*•]+\s*", "", line)
    line = re.sub(r"^\s*\d+[.)]\s*", "", line)
    return line.strip()


def _extract_short_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("|"):
            return []
        if line.startswith("#"):
            continue
        lower = line.lower().strip()
        if re.match(r"^(dưới đây|sau đây|gồm|bao gồm|cụ thể|ví dụ)\b", lower):
            continue
        cleaned = _strip_md_prefix(line)
        if cleaned:
            lines.append(cleaned)
    return lines


def _looks_like_already_table(text: str) -> bool:
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    for i in range(len(lines) - 1):
        first = lines[i].strip()
        second = lines[i + 1].strip()
        if first.startswith("|") and second.startswith("|"):
            sep = second.replace(" ", "")
            if re.fullmatch(r"\|?[:\-|]+\|?", sep):
                return True
    return False


def _parse_key_value_line(line: str) -> tuple[str, str] | None:
    line = _strip_md_prefix(line)
    for sep in [":", " - ", " – ", " — "]:
        if sep in line:
            left, right = line.split(sep, 1)
            left = left.strip(" -*•\t")
            right = right.strip(" -*•\t")
            if left and right:
                return left, right
    return None


def _looks_like_short_uniform_lines(lines: list[str]) -> bool:
    if not lines:
        return False
    if len(lines) < 3 or len(lines) > 10:
        return False
    if any(len(line) > 160 for line in lines):
        return False
    kv_count = sum(1 for x in lines if _parse_key_value_line(x) is not None)
    title_count = sum(
        1 for x in lines
        if re.match(r"^(ngành|chương trình|khoa)\b", x.lower())
    )
    if title_count >= 2 and kv_count >= 4:
        return True
    colon_lines = sum(1 for x in lines if ":" in x)
    dash_lines = sum(1 for x in lines if " - " in x or " – " in x or " — " in x)
    score = 0
    if colon_lines >= max(2, len(lines) // 2):
        score += 1
    if dash_lines >= max(2, len(lines) // 2):
        score += 1
    word_counts = [len(x.split()) for x in lines]
    if word_counts and (max(word_counts) - min(word_counts) <= 14):
        score += 1
    return score >= 2


def _to_table_from_pairs(lines: list[str], default_left="Mục", default_right="Chi tiết") -> str | None:
    pairs: list[tuple[str, str]] = []
    for line in lines:
        parsed = _parse_key_value_line(line)
        if not parsed:
            return None
        pairs.append(parsed)
    if len(pairs) < 2:
        return None
    if any(len(left) > 60 or len(right) > 120 for left, right in pairs):
        return None
    out = [f"| {default_left} | {default_right} |", "|---|---|"]
    for left, right in pairs:
        out.append(f"| {left} | {right} |")
    return "\n".join(out)


def _to_table_from_grouped_blocks(lines: list[str]) -> str | None:
    groups: list[dict] = []
    current_title: str | None = None
    current_details: list[tuple[str, str]] = []

    def flush():
        nonlocal current_title, current_details
        if current_title and current_details:
            groups.append({"title": current_title, "details": current_details[:]})
        current_title = None
        current_details = []

    for line in lines:
        parsed = _parse_key_value_line(line)
        if parsed is None:
            maybe_title = _strip_md_prefix(line)
            if re.match(r"^(ngành|chương trình|khoa)\b", maybe_title.lower()):
                flush()
                current_title = maybe_title
            else:
                return None
            continue
        if not current_title:
            return None
        left, right = parsed
        current_details.append((left.strip(), right.strip()))

    flush()

    if len(groups) < 2 or len(groups) > 10:
        return None
    key_sets = [tuple(k for k, _ in g["details"]) for g in groups]
    first_keys = key_sets[0]
    if not first_keys:
        return None
    if not all(keys == first_keys for keys in key_sets):
        return None

    headers = ["Tên"] + list(first_keys)
    out = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for g in groups:
        detail_map = {k: v for k, v in g["details"]}
        row = [g["title"]] + [detail_map.get(k, "") for k in first_keys]
        if any(len(cell) > 120 for cell in row):
            return None
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def _auto_convert_short_answer_to_table(text: str, question: str) -> str:
    if not text:
        return text
    if _looks_like_already_table(text):
        return text
    lines = _extract_short_lines(text)
    if not _looks_like_short_uniform_lines(lines):
        return text

    grouped_table = _to_table_from_grouped_blocks(lines)
    if grouped_table:
        return grouped_table

    if _wants_table_answer(question):
        q = _normalize_text(question)
        default_left = "Mục"
        default_right = "Chi tiết"
        if "diem chuan" in q:
            default_left, default_right = "Ngành/Mục", "Điểm"
        elif "hoc phi" in q:
            default_left, default_right = "Mục", "Học phí"
        elif "chung chi" in q or "tuong duong" in q:
            default_left, default_right = "Chứng chỉ/Mục", "Chi tiết"

        pair_table = _to_table_from_pairs(lines, default_left=default_left, default_right=default_right)
        if pair_table:
            return pair_table

    return text


def _table_block_is_too_wide(block: list[str]) -> bool:
    if not block:
        return False
    if any(len((ln or "").strip()) > 220 for ln in block):
        return True
    if len(block) > 12:
        return True
    for ln in block[2:]:
        raw = ln.strip().strip("|")
        cells = [c.strip() for c in raw.split("|")]
        if len(cells) <= 1:
            return True
        if any(len(c) > 160 for c in cells):
            return True
        if sum(1 for c in cells if len(c) > 90) >= 2:
            return True
    return False


def _convert_table_block_to_bullets(block: list[str]) -> str:
    if len(block) < 3:
        return "\n".join(block)
    header_line = block[0].strip().strip("|")
    headers = [h.strip() for h in header_line.split("|") if h.strip()]
    out: list[str] = []
    for row in block[2:]:
        raw = row.strip().strip("|")
        cells = [c.strip() for c in raw.split("|")]
        cells = [c for c in cells if c]
        if not cells:
            continue
        if len(headers) >= 2 and len(cells) >= 2:
            title = cells[0]
            detail = " | ".join(cells[1:]).strip()
            if title:
                out.append(f"- **{title}**")
                if detail:
                    out.append(f"  - {detail}")
        else:
            out.append(f"- {' | '.join(cells)}")
    return "\n".join(out).strip()


def _repair_broken_markdown_tables(text: str) -> str:
    if not text or not _looks_like_already_table(text):
        return text
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if line.startswith("|") and nxt.startswith("|") and re.fullmatch(r"\|?[:\-|]+\|?", nxt.replace(" ", "")):
            block = [lines[i], lines[i + 1]]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            if _table_block_is_too_wide(block):
                out.append(_convert_table_block_to_bullets(block))
            else:
                out.extend(block)
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out).strip()


def _is_reference_followup(question: str) -> bool:
    q = _normalize_text(question)
    patterns = [
        r"\by\s+(?:so\s+)?\d+\b",
        r"\bmuc\s+(?:so\s+)?\d+\b",
        r"\bdong\s+(?:so\s+)?\d+\b",
        r"\bkhoan\s+(?:so\s+)?\d+\b",
        r"\bdieu\s+(?:so\s+)?\d+\b",
        r"\btruong\s+hop\s+(?:so\s+)?\d+\b",
        r"\by\s+(?:dau\s+tien|thu\s+nhat|thu\s+hai|thu\s+ba|thu\s+tu)\b",
        r"\by\s+tren\b", r"\by\s+phia\s+tren\b", r"\bmuc\s+tren\b",
        r"\bdong\s+tren\b", r"\bcai\s+do\b", r"\bnoi\s+dung\s+do\b",
        r"\bphan\s+do\b", r"\bdo\s+la\s+gi\b",
        r"\bgiai\s+thich\s+(?:them|ro\s+hon|cu\s+the\s+hon|chi\s+tiet\s+hon)\b",
        r"\bno\s+la\s+gi\b", r"\bno\s+co\s+nghia\b",
        r"\bve\s+dieu\s+nay\b", r"\bve\s+viec\s+nay\b",
    ]
    return any(re.search(p, q) for p in patterns)


def _last_meaningful_model_answer(history: list[dict]) -> str:
    for msg in reversed(history or []):
        if msg.get("role") == "model":
            content = (msg.get("content") or "").strip()
            if content:
                return content
    return ""


def _last_meaningful_user_question(history: list[dict]) -> str:
    for msg in reversed(history or []):
        if msg.get("role") == "user":
            content = (msg.get("content") or "").strip()
            if content:
                return content
    return ""


def _extract_referenced_item(question: str, previous_answer: str) -> str:
    q = _normalize_text(question)
    prev_lines = [ln.strip() for ln in (previous_answer or "").splitlines() if ln.strip()]

    m = re.search(r"\b(?:y|muc|dong|khoan|dieu|truong\s+hop)\s+(?:so\s+)?(\d+)\b", q)

    ordinal_map = {"nhat": 1, "hai": 2, "ba": 3, "tu": 4, "nam": 5}
    if not m:
        mo = re.search(r"\by\s+thu\s+(\w+)\b", q)
        if mo and mo.group(1) in ordinal_map:
            target_idx = ordinal_map[mo.group(1)]
            m = None
        else:
            target_idx = None
    else:
        target_idx = int(m.group(1))

    if target_idx is not None:
        block_lines: list[str] = []
        inside = False

        for ln in prev_lines:
            cleaned = _strip_md_prefix(ln)

            is_heading = bool(
                re.match(rf"^{target_idx}[.)]\s+", cleaned)
                or re.match(rf"^{target_idx}\.\d", cleaned)
                or re.match(rf"^[Ýý]\s*{target_idx}\b", cleaned)
                or re.match(rf"^[Mm]ục\s*{target_idx}\b", cleaned)
                or re.match(rf"^[Tt]rường\s+hợp\s*{target_idx}\b", cleaned)
            )

            is_other_heading = bool(
                re.match(r"^\d+[.)]\s+\S", cleaned)
                or re.match(r"^\d+\.\d", cleaned)
                or re.match(r"^[Ýý]\s*\d+\b", cleaned)
                or re.match(r"^[Mm]ục\s*\d+\b", cleaned)
            )

            if is_heading:
                inside = True
                block_lines = [cleaned]
                continue

            if inside:
                if is_other_heading and not is_heading:
                    break
                block_lines.append(cleaned)

        if block_lines:
            return "\n".join(block_lines)

        for ln in prev_lines:
            cleaned = _strip_md_prefix(ln)
            if str(target_idx) in cleaned and len(cleaned) >= 8:
                return cleaned

    if any(x in q for x in [
        "y tren", "y phia tren", "muc tren", "dong tren",
        "phan do", "noi dung do", "cai do", "no la gi", "no co nghia",
        "ve dieu nay", "ve viec nay",
    ]):
        meaningful = [ln for ln in prev_lines if len(_strip_md_prefix(ln)) >= 12]
        if meaningful:
            return "\n".join(meaningful[:6])

    return ""


def _rewrite_followup_question(question: str, history: list[dict]) -> str:
    if not _is_reference_followup(question):
        return question

    previous_answer = _last_meaningful_model_answer(history)
    previous_user = _last_meaningful_user_question(history[:-1] if history else [])
    referenced_item = _extract_referenced_item(question, previous_answer)

    if referenced_item and previous_user:
        return (
            f"Dựa trên nội dung sau đây (trích từ câu trả lời về '{previous_user}'):\n\n"
            f"{referenced_item}\n\n"
            f"Hãy giải thích rõ hơn theo yêu cầu: {question}"
        )
    if referenced_item:
        return (
            f"Dựa trên nội dung sau:\n\n{referenced_item}\n\n"
            f"Hãy giải thích rõ hơn: {question}"
        )
    if previous_answer and previous_user:
        snippet = previous_answer.replace("\n", " ").strip()
        if len(snippet) > 400:
            snippet = snippet[:400].rstrip() + "..."
        return (
            f"Tiếp nối chủ đề: '{previous_user}'.\n"
            f"Câu trả lời trước: '{snippet}'.\n"
            f"Câu hỏi tiếp theo: {question}"
        )
    return question


def _postprocess_answer(text: str, question: str) -> str:
    text = (text or "").strip()
    if not text:
        return text
    text = (
        text.replace("\r\n", "\n")
        .replace("<br>", "\n")
        .replace("<br/>", "\n")
        .replace("<br />", "\n")
    )
    text = _auto_convert_short_answer_to_table(text, question)
    text = _repair_broken_markdown_tables(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _trim_history_by_token_budget(
    history: list[dict],
    budget: int = HISTORY_TOKEN_BUDGET,
) -> list[dict]:
    if not history:
        return []

    sized = [(msg, _estimate_tokens(msg.get("content", ""))) for msg in history]

    total = sum(s for _, s in sized)
    if total <= budget:
        return history

    keep_head = min(2, len(sized))
    head = [msg for msg, _ in sized[:keep_head]]
    head_tokens = sum(s for _, s in sized[:keep_head])

    tail_budget = budget - head_tokens
    tail: list[dict] = []
    tail_tokens = 0

    for msg, tokens in reversed(sized[keep_head:]):
        if tail_tokens + tokens > tail_budget:
            break
        tail.insert(0, msg)
        tail_tokens += tokens

    trimmed = head + tail
    if len(trimmed) < len(history):
        logger.info(
            "History trimmed: %d → %d messages (~%d tokens kept)",
            len(history), len(trimmed), head_tokens + tail_tokens,
        )
    return trimmed


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
            update(Session).where(Session.id == session_id).values(title=title)
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
    return _postprocess_answer(text.strip(), question)


async def _stream_text_answer(
    *,
    session_id: str,
    question: str,
    history: list[dict],
) -> AsyncGenerator[str, None]:
    async with AsyncSessionLocal() as db:
        try:
            effective_question = _rewrite_followup_question(question, history)

            is_self_contained_followup = (
                _is_reference_followup(question)
                and effective_question != question
                and _extract_referenced_item(question, _last_meaningful_model_answer(history)) != ""
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
                    if c.payload and c.payload.get("doc_name")
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

                if has_table_context or _wants_table_answer(effective_question):
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

            trimmed_history = _trim_history_by_token_budget(history, HISTORY_TOKEN_BUDGET)

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

            full = _postprocess_answer(full, effective_question)

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
        answer = _postprocess_answer(answer, user_prompt)
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