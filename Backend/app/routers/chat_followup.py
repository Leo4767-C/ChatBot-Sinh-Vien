"""
chat_followup.py — Xử lý câu hỏi follow-up: phát hiện tham chiếu,
rewrite câu hỏi, và quản lý history token budget.
"""
import logging
import re

from app.routers.chat_formatters import normalize_text, strip_md_prefix

logger = logging.getLogger(__name__)

HISTORY_TOKEN_BUDGET = 12_000


def is_reference_followup(question: str) -> bool:
    q = normalize_text(question)
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


def last_meaningful_model_answer(history: list[dict]) -> str:
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


def extract_referenced_item(question: str, previous_answer: str) -> str:
    q = normalize_text(question)
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
            cleaned = strip_md_prefix(ln)

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
            cleaned = strip_md_prefix(ln)
            if str(target_idx) in cleaned and len(cleaned) >= 8:
                return cleaned

    if any(x in q for x in [
        "y tren", "y phia tren", "muc tren", "dong tren",
        "phan do", "noi dung do", "cai do", "no la gi", "no co nghia",
        "ve dieu nay", "ve viec nay",
    ]):
        meaningful = [ln for ln in prev_lines if len(strip_md_prefix(ln)) >= 12]
        if meaningful:
            return "\n".join(meaningful[:6])

    return ""


def rewrite_followup_question(question: str, history: list[dict]) -> str:
    if not is_reference_followup(question):
        return question

    previous_answer = last_meaningful_model_answer(history)
    previous_user = _last_meaningful_user_question(history[:-1] if history else [])
    referenced_item = extract_referenced_item(question, previous_answer)

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


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def trim_history_by_token_budget(
    history: list[dict],
    budget: int = HISTORY_TOKEN_BUDGET,
) -> list[dict]:
    if not history:
        return []

    sized = [(msg, estimate_tokens(msg.get("content", ""))) for msg in history]

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
