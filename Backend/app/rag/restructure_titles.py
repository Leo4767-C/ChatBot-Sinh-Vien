import logging
import re
from pathlib import Path
from typing import Any

from unstructured.partition.auto import partition
from unstructured.partition.html import partition_html
from unstructured.partition.md import partition_md
from unstructured.partition.text import partition_text

log = logging.getLogger(__name__)


class Chunk:
    def __init__(
        self,
        title_id: str | None = None,
        title: str = "",
        content: str = "",
        pages: set[int] | None = None,
    ):
        self.title_id = title_id
        self.title = title
        self.content = content
        self.pages = pages or set()

    def get_pages_list(self) -> list[int]:
        return sorted(list(self.pages))

    def add_page_ref(self, page: int | None):
        if page is None:
            return
        try:
            page = int(page)
            if page > 0:
                self.pages.add(page)
        except Exception:
            return

    def to_dict(self):
        return {
            "title_id": self.title_id,
            "title": self.title,
            "content": self.content,
            "pages": sorted(list(self.pages)),
        }


def _safe_page_number(value: Any) -> int:
    try:
        page = int(value)
        return page if page > 0 else 1
    except Exception:
        return 1


def _make_title_id(title: str, page_number: int) -> str:
    return str(abs(hash(f"{title.strip()}::{page_number}")))


def _clean_text(text: str) -> str:
    text = (text or "").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _partition_file(file_path: Path):
    file_ext = file_path.suffix.lower()

    if file_ext == ".md":
        return partition_md(filename=str(file_path))
    if file_ext in [".html", ".htm"]:
        return partition_html(filename=str(file_path))
    if file_ext == ".txt":
        return partition_text(filename=str(file_path))

    return partition(filename=str(file_path))


def _roman_to_int(token: str) -> int:
    roman_map = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    token = token.lower()
    total = 0
    prev = 0
    for ch in reversed(token):
        val = roman_map.get(ch, 0)
        if val < prev:
            total -= val
        else:
            total += val
            prev = val
    return total


def _extract_heading_level(text: str) -> int | None:
    """
    Heuristic level detector:
    1 -> Chương / Phần / Mục lớn / I. / 1.
    2 -> 1.1 / 1.1.
    3 -> 1.1.1 / 1.1.1.
    4 -> deeper numbered
    """
    t = _clean_text(text)
    if not t:
        return None

    lower = t.lower()

    if lower.startswith(("chương ", "chuong ", "phần ", "phan ")):
        return 1

    if lower.startswith(("mục ", "muc ")):
        return 2

    m_roman = re.match(r"^([ivxlcdm]+)[\.\)]\s+", lower)
    if m_roman and _roman_to_int(m_roman.group(1)) > 0:
        return 1

    m_num = re.match(r"^(\d+(?:\.\d+){0,5})[\.\)]?\s+", t)
    if m_num:
        depth = m_num.group(1).count(".")
        if depth == 0:
            return 1
        if depth == 1:
            return 2
        if depth == 2:
            return 3
        return 4

    return None


def _looks_like_heading(text: str, category: str = "") -> bool:
    t = _clean_text(text)
    if not t:
        return False

    if category == "Title":
        return True

    if len(t) > 180:
        return False

    if _extract_heading_level(t) is not None:
        return True

    if t.isupper() and len(t) <= 120:
        return True

    if re.match(r"^(Điều|Khoản|Mục|Phần|Chương)\b", t, flags=re.IGNORECASE):
        return True

    return False


def _heading_level(text: str, category: str = "") -> int:
    level = _extract_heading_level(text)
    if level is not None:
        return level

    t = _clean_text(text)

    if category == "Title":
        return 2 if len(t) <= 100 else 3

    if t.isupper() and len(t) <= 120:
        return 1

    if re.match(r"^(Điều)\b", t, flags=re.IGNORECASE):
        return 2

    if re.match(r"^(Khoản)\b", t, flags=re.IGNORECASE):
        return 3

    return 3


def _flat_txt_fallback(file_path: Path) -> dict:
    text = file_path.read_text(encoding="utf-8").strip()
    return {
        "titleId": _make_title_id(file_path.stem, 1),
        "title": file_path.stem,
        "content": text,
        "page_number": 1,
        "children": [],
        "pages": [1],
    }


def _new_node(title: str, page_number: int) -> dict:
    return {
        "titleId": _make_title_id(title, page_number),
        "title": title,
        "content": "",
        "page_number": page_number,
        "children": [],
        "pages": [page_number] if page_number > 0 else [],
    }


def _append_content(node: dict, text: str, page_number: int):
    text = _clean_text(text)
    if not text:
        return

    if node.get("content"):
        node["content"] += "\n\n" + text
    else:
        node["content"] = text

    node.setdefault("pages", [])
    if page_number > 0 and page_number not in node["pages"]:
        node["pages"].append(page_number)


def _ensure_root(file_path: Path) -> dict:
    return {
        "titleId": _make_title_id(file_path.stem, -1),
        "title": file_path.stem,
        "content": "",
        "page_number": -1,
        "children": [],
        "pages": [],
    }


def _build_tree_rule_based(elements: list[Any], file_path: Path) -> dict:
    root = _ensure_root(file_path)
    stack: list[tuple[int, dict]] = [(0, root)]
    current_node = root
    current_page = 1

    for el in elements:
        text = _clean_text(getattr(el, "text", "") or "")
        if not text:
            continue

        metadata = getattr(el, "metadata", None)
        category = getattr(el, "category", "") or ""
        page_number = getattr(metadata, "page_number", None) if metadata else None
        if page_number:
            current_page = _safe_page_number(page_number)

        if _looks_like_heading(text, category):
            level = _heading_level(text, category)
            node = _new_node(text, current_page)

            while stack and stack[-1][0] >= level:
                stack.pop()

            parent = stack[-1][1] if stack else root
            parent.setdefault("children", []).append(node)
            stack.append((level, node))
            current_node = node
        else:
            _append_content(current_node, text, current_page)

    return root


def build_chunks_dict(content_items: list[dict[str, Any]]) -> dict[str, Chunk]:
    chunks: dict[str, Chunk] = {}

    for item in content_items:
        title_id = item.get("title_id")
        if not title_id:
            continue

        if title_id not in chunks:
            chunks[title_id] = Chunk(
                title_id=title_id,
                content="",
                pages=set(),
            )

        text = _clean_text(item.get("text") or "")
        if text:
            if chunks[title_id].content:
                chunks[title_id].content += "\n\n" + text
            else:
                chunks[title_id].content = text

        page_number = item.get("page_number")
        if page_number:
            chunks[title_id].add_page_ref(_safe_page_number(page_number))

    return chunks


def merge_content(node: dict, chunks: dict[str, Chunk], depth: int = 0):
    if not isinstance(node, dict):
        return node

    title_id = node.get("titleId")
    if title_id in chunks:
        chunk = chunks[title_id]
        if not node.get("content"):
            node["content"] = chunk.content
        node["pages"] = chunk.get_pages_list()
    else:
        node.setdefault("content", "")
        node.setdefault("pages", [])

    children = node.get("children", [])
    if isinstance(children, list):
        for child in children:
            merge_content(child, chunks, depth + 1)

    return node


def chunk_by_title(file_path: str | Path) -> dict:
    file_path = Path(file_path)
    file_ext = file_path.suffix.lower()

    supported_exts = {".txt", ".md", ".html", ".htm", ".pdf", ".docx", ".doc"}
    if file_ext not in supported_exts:
        raise ValueError(
            f"Định dạng file không được hỗ trợ: {file_ext}. "
            "Vui lòng cung cấp file Text (.txt), Markdown (.md), HTML (.html) hoặc PDF/DOCX."
        )

    if file_ext == ".txt":
        return _flat_txt_fallback(file_path)

    elements = _partition_file(file_path)

    if not elements:
        return _ensure_root(file_path)

    structured = _build_tree_rule_based(elements, file_path)

    if not structured.get("children"):
        all_text = "\n\n".join(
            _clean_text(getattr(el, "text", "") or "")
            for el in elements
            if _clean_text(getattr(el, "text", "") or "")
        ).strip()
        structured["content"] = all_text
        structured["pages"] = sorted(
            list(
                {
                    _safe_page_number(getattr(getattr(el, "metadata", None), "page_number", 1))
                    for el in elements
                    if getattr(el, "metadata", None) is not None
                }
            )
        )
        return structured

    structured.setdefault("titleId", _make_title_id(file_path.stem, -1))
    structured.setdefault("title", file_path.stem)
    structured.setdefault("content", "")
    structured.setdefault("page_number", -1)
    structured.setdefault("children", [])
    structured.setdefault("pages", [])

    return structured