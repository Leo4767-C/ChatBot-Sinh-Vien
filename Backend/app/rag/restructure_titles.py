import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI

from unstructured.partition.auto import partition
from unstructured.partition.html import partition_html
from unstructured.partition.md import partition_md
from unstructured.partition.text import partition_text

from app.core.config import settings

log = logging.getLogger(__name__)

guide_v2 = """
{
  "titleId": "f9c914bbe5fe7cce8avjfkdkdkdkdkd",
  "title": "Tài liệu ôn tập",
  "content": "",
  "page_number": -1,
  "children": [
    {
      "titleId": "f9c914bbe5fe7cce8abde153f607eaea",
      "title": "Chương 1: Giới thiệu",
      "content": "",
      "page_number": 1,
      "children": [
        {
          "titleId": "ab2c809cc6f2cd1f114dd9fddbdae7b2",
          "title": "1.1. Khái niệm cơ bản",
          "content": "",
          "page_number": 1,
          "children": []
        }
      ]
    }
  ]
}
"""

load_dotenv()


def format_prompt(raw_data: dict[str, list[Any]]) -> dict[str, str]:
    prompt = (
        "Bạn là trợ lý chuyên cấu trúc lại dữ liệu tiêu đề tài liệu tiếng Việt.\n"
        "Bạn được cung cấp một dictionary Python, trong đó:\n"
        "- Key là ID duy nhất của tiêu đề.\n"
        "- Value là một list gồm [title, page_number].\n"
        "Các tiêu đề có thể có hoặc không có đánh số đề mục.\n\n"
        f"Nhiệm vụ: chuyển dữ liệu này thành JSON đúng cấu trúc sau:\n```{guide_v2}```\n\n"
        "Quy tắc:\n"
        "- titleId: ID duy nhất của đề mục.\n"
        "- title: tên đề mục.\n"
        "- content: luôn để chuỗi rỗng.\n"
        "- page_number: số trang tương ứng.\n"
        "- children: danh sách đề mục con.\n\n"
        f"Dữ liệu đầu vào:\n```{raw_data}```\n\n"
        "Chỉ trả về JSON hợp lệ, không giải thích thêm."
    )
    return {"prompt": prompt}


def build_chain():
    api_key = (
        getattr(settings, "GEMINI_API_KEY", None)
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
    )
    model = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0,
        api_key=api_key,
    )
    chain = (
        RunnableLambda(format_prompt)
        | (lambda x: x["prompt"])
        | model
        | JsonOutputParser()
    )
    return chain


def restructure(raw_data: dict[str, list[Any]]) -> dict:
    chain = build_chain()
    return chain.invoke(raw_data)


class Chunk:
    def __init__(
        self,
        title_id: str | None = None,
        title: str = "",
        content: str = "",
        image_paths: set[str] | None = None,
        pages: set[int] | None = None,
    ):
        self.title_id = title_id
        self.title = title
        self.content = content
        self.image_paths = image_paths
        self.pages = pages

    def get_pages_list(self) -> list[int]:
        return [] if self.pages is None else list(self.pages)

    def get_image_paths_list(self) -> list[str]:
        return [] if self.image_paths is None else list(self.image_paths)

    def add_image_path(self, path: str | None):
        if not path:
            return
        if self.image_paths is None:
            self.image_paths = set()
        self.image_paths.add(path)

    def add_page_ref(self, page: int | None):
        if page is None or page < 1:
            return
        if self.pages is None:
            self.pages = set()
        self.pages.add(page)

    def to_dict(self):
        return {
            "title_id": self.title_id,
            "title": self.title,
            "content": self.content,
            "image_paths": [] if self.image_paths is None else list(self.image_paths),
            "pages": [] if self.pages is None else list(self.pages),
        }


def _safe_page_number(value: Any) -> int:
    try:
        page = int(value)
        return page if page > 0 else 1
    except Exception:
        return 1


def _make_title_id(title: str, page_number: int) -> str:
    return str(abs(hash(f"{title.strip()}::{page_number}")))


def _is_title_element(el: Any) -> bool:
    category = getattr(el, "category", "") or ""
    text = (getattr(el, "text", "") or "").strip()

    if category == "Title":
        return True

    if not text:
        return False

    if len(text) <= 120 and (
        text.isupper()
        or text.startswith("Chương ")
        or text.startswith("CHƯƠNG ")
        or text.startswith("Phần ")
        or text.startswith("PHẦN ")
        or text.startswith("Mục ")
        or text.startswith("MỤC ")
    ):
        return True

    numbered_prefixes = tuple(str(i) for i in range(1, 21))
    if text[0:1].isdigit() and any(text.startswith(p) for p in numbered_prefixes):
        return True

    return False


def build_chunks_dict(content_items: list[dict[str, Any]]) -> dict[str, Chunk]:
    chunks: dict[str, Chunk] = {}

    for item in content_items:
        title_id = item.get("title_id")
        if not title_id:
            continue

        if title_id not in chunks:
            chunks[title_id] = Chunk(title_id=title_id, content="", pages=set(), image_paths=set())

        text = (item.get("text") or "").strip()
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
    """
    Gắn content/pages/image_paths từ chunks vào cây cấu trúc.
    """
    if not isinstance(node, dict):
        return node

    title_id = node.get("titleId")
    if title_id in chunks:
        chunk = chunks[title_id]
        if not node.get("content"):
            node["content"] = chunk.content
        node["pages"] = chunk.get_pages_list()
        node["image_paths"] = chunk.get_image_paths_list()
    else:
        node.setdefault("content", "")
        node.setdefault("pages", [])
        node.setdefault("image_paths", [])

    children = node.get("children", [])
    if isinstance(children, list):
        for child in children:
            merge_content(child, chunks, depth + 1)

    return node


def _flat_txt_fallback(file_path: Path) -> dict:
    text = file_path.read_text(encoding="utf-8").strip()
    return {
        "titleId": _make_title_id(file_path.stem, 1),
        "title": file_path.stem,
        "content": text,
        "page_number": 1,
        "children": [],
        "pages": [1],
        "image_paths": [],
    }


def _partition_file(file_path: Path):
    file_ext = file_path.suffix.lower()

    if file_ext == ".md":
        return partition_md(filename=str(file_path))
    if file_ext in [".html", ".htm"]:
        return partition_html(filename=str(file_path))
    if file_ext == ".txt":
        return partition_text(filename=str(file_path))

    # pdf/docx/... để auto xử lý
    return partition(filename=str(file_path))


def chunk_by_title(file_path: str | Path) -> dict:
    file_path = Path(file_path)
    file_ext = file_path.suffix.lower()

    supported_exts = {".txt", ".md", ".html", ".htm", ".pdf", ".docx", ".doc"}
    if file_ext not in supported_exts:
        raise ValueError(
            f"Định dạng file không được hỗ trợ: {file_ext}. "
            "Vui lòng cung cấp file Text (.txt), Markdown (.md), HTML (.html) hoặc PDF/DOCX."
        )

    # Với txt: ưu tiên fallback đơn giản để ingest ổn định
    if file_ext == ".txt":
        return _flat_txt_fallback(file_path)

    elements = _partition_file(file_path)

    raw_titles: dict[str, list[Any]] = {}
    content_items: list[dict[str, Any]] = []
    current_title_id: str | None = None
    current_page = 1

    for el in elements:
        text = (getattr(el, "text", None) or "").strip()
        if not text:
            continue

        metadata = getattr(el, "metadata", None)
        page_number = getattr(metadata, "page_number", None) if metadata else None
        if page_number:
            current_page = _safe_page_number(page_number)

        if _is_title_element(el):
            title_id = _make_title_id(text, current_page)
            raw_titles[title_id] = [text, current_page]
            current_title_id = title_id
        else:
            content_items.append(
                {
                    "title_id": current_title_id,
                    "text": text,
                    "page_number": current_page,
                }
            )

    # Nếu không bóc được title nào thì fallback thành 1 chunk
    if not raw_titles:
        all_text = "\n\n".join(
            (getattr(el, "text", "") or "").strip()
            for el in elements
            if (getattr(el, "text", "") or "").strip()
        ).strip()

        return {
            "titleId": _make_title_id(file_path.stem, 1),
            "title": file_path.stem,
            "content": all_text,
            "page_number": 1,
            "children": [],
            "pages": [1],
            "image_paths": [],
        }

    try:
        structured = restructure(raw_titles)
    except Exception as e:
        log.warning("LLM restructure failed, fallback tree 1 cấp: %s", e)
        structured = {
            "titleId": _make_title_id(file_path.stem, -1),
            "title": file_path.stem,
            "content": "",
            "page_number": -1,
            "children": [
                {
                    "titleId": title_id,
                    "title": title_page[0],
                    "content": "",
                    "page_number": _safe_page_number(title_page[1]),
                    "children": [],
                }
                for title_id, title_page in raw_titles.items()
            ],
        }

    chunks = build_chunks_dict(content_items)
    structured = merge_content(structured, chunks)

    structured.setdefault("titleId", _make_title_id(file_path.stem, -1))
    structured.setdefault("title", file_path.stem)
    structured.setdefault("content", "")
    structured.setdefault("page_number", -1)
    structured.setdefault("children", [])
    structured.setdefault("pages", [])
    structured.setdefault("image_paths", [])

    return structured