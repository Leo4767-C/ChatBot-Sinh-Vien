"""
chat_formatters.py — Xử lý định dạng text, chuyển đổi bảng Markdown,
sửa bảng lỗi, và hậu xử lý câu trả lời từ LLM.
"""
import re
import unicodedata


def normalize_text(text: str) -> str:
    text = (text or "").lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def wants_table_answer(question: str) -> bool:
    q = normalize_text(question)
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


def strip_md_prefix(line: str) -> str:
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
        cleaned = strip_md_prefix(line)
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
    line = strip_md_prefix(line)
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
            maybe_title = strip_md_prefix(line)
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

    if wants_table_answer(question):
        q = normalize_text(question)
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


def postprocess_answer(text: str, question: str) -> str:
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
