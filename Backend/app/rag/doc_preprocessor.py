import copy
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Union

import tiktoken
from openpyxl.reader.excel import load_workbook

from app.core.config import settings
from app.rag.converters import DocumentConverter, convert_to_pdf
from app.rag.restructure_titles import chunk_by_title, chunk_manually_doc
from app.storage.storage_service import get_storage
from app.utils.helpers import project_root

os.environ["CUDA_VISIBLE_DEVICES"] = settings.CUDA_VISIBLE_DEVICES

log = logging.getLogger(__name__)

_SENT_RE = re.compile(r"(?<!\b\d)(?<!\b\d\d)(?<!\b[a-zA-Z])(?<=[.!?])\s+")

_CONVERTERS: Dict[str, DocumentConverter] = {
    ".docx": convert_to_pdf,
}


def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENT_RE.split((text or "").strip()) if s.strip()]


def count_tokens(text: str, tokenizer) -> int:
    return len(tokenizer.encode(text))


def chunk_doc(doc: Dict[str, Any], model: str) -> List[dict]:
    from app.llm.llm_service import llm_client

    path: List[str] = []
    current_chunk: Dict[str, Any] = {
        "text": "",
        "pages": set(),
    }
    chunks: List[Dict[str, Any]] = []

    def reset_buffer():
        nonlocal current_chunk
        current_chunk = {
            "text": "",
            "pages": set(),
        }

    def header() -> str:
        return ".\n".join([p for p in path if p])

    def flush() -> None:
        nonlocal current_chunk
        text = current_chunk["text"].strip()
        if text:
            chunks.append(
                {
                    "text": text,
                    "pages": sorted(list(current_chunk["pages"])),
                }
            )
            reset_buffer()

    def ensure_header() -> None:
        if not current_chunk["text"]:
            h = header()
            current_chunk["text"] = h if h else ""

    def token_len(text: str) -> int:
        try:
            return llm_client.count_tokens(text)
        except Exception:
            return max(1, int(len(text.split()) * 1.3))

    def add_piece(txt: str, pages: List[int]) -> None:
        nonlocal current_chunk

        txt = (txt or "").strip()
        if not txt:
            return

        ensure_header()
        connector = "\n" if current_chunk["text"] and not current_chunk["text"].endswith("\n") else ""
        piece = connector + txt

        token_count = token_len(current_chunk["text"]) + token_len(piece)
        chunk_size = int(getattr(settings, "CHUNK_SIZE", 800))
        overlap = max(0, int(getattr(settings, "OVERLAP", 80)))

        if token_count > chunk_size and current_chunk["text"].strip():
            if overlap > 0:
                current_chunk["text"] += piece[:overlap]
            flush()
            ensure_header()
            if overlap > 0:
                piece = piece[overlap:]

        current_chunk["text"] += piece
        current_chunk["pages"].update(pages or [])

    def dfs(node: Dict[str, Any]) -> None:
        nonlocal current_chunk

        if not isinstance(node, dict):
            return

        node_pages = node.get("pages", []) or []

        node_title = (node.get("title") or "").strip()
        if node_title:
            path.append(node_title)

        if current_chunk["text"] and node_title:
            add_piece(node_title + ".", node_pages)

        current_chunk["pages"].update(node_pages)

        for sent in split_sentences(node.get("content", "")):
            add_piece(sent, node_pages)

        for child in node.get("children", []) or []:
            backup_chunk = copy.deepcopy(current_chunk)
            backup_chunks = chunks[:]
            backup_path = path[:]

            dfs(child)

            if len(chunks) > len(backup_chunks):
                current_chunk = backup_chunk
                chunks[:] = backup_chunks
                path[:] = backup_path
                flush()
                dfs(child)

        if node_title and path:
            path.pop()

    dfs(doc)
    flush()
    return chunks


def chunk_excel(file: Path, tokenizer: tiktoken.Encoding, max_len: int = 600) -> list[dict]:
    def detect_excel_header(ws, scan=5):
        scores = []
        for r in range(1, scan + 1):
            row = ws[r]
            bold_count = sum(1 for cell in row if cell.font and cell.font.bold)
            text_count = sum(1 for cell in row if isinstance(cell.value, str))
            number_count = sum(1 for cell in row if isinstance(cell.value, (int, float)))
            score = bold_count * 3 + text_count * 2 - number_count
            scores.append((r, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[0][0]

    def get_real_data_range(ws):
        max_row = 0
        max_col = 0
        for row in ws.iter_rows(values_only=True):
            row_has_value = False
            for idx, cell in enumerate(row, start=1):
                if cell not in (None, ""):
                    row_has_value = True
                    max_col = max(max_col, idx)
            if row_has_value:
                max_row += 1
        return max_row, max_col

    def read_ws_data(ws, max_row, max_col):
        lines = []
        for r in range(1, max_row + 1):
            row = ws[r]
            processed_cells = []
            for c in range(1, max_col + 1):
                cell = row[c - 1].value
                cell_str = "" if cell is None else str(cell)
                if ("," in cell_str) or ("\n" in cell_str) or ('"' in cell_str):
                    cell_str = cell_str.replace('"', '""')
                    cell_str = f'"{cell_str}"'
                processed_cells.append(cell_str)
            lines.append(",".join(processed_cells))
        return lines

    chunks = []
    wb = load_workbook(file)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        header_row = detect_excel_header(ws)
        max_row, max_col = get_real_data_range(ws)
        lines = read_ws_data(ws, max_row, max_col)

        text = f"{file.stem} - {sheet_name}:"

        if header_row > 1:
            for i in range(0, header_row - 1):
                token_count = count_tokens(text, tokenizer) + count_tokens(lines[i], tokenizer)
                if token_count > max_len:
                    chunks.append({"text": text, "pages": []})
                    text = f"{file.stem} - {sheet_name}:"
                text += f"\n{lines[i]}"
            chunks.append({"text": text, "pages": []})
            text = f"{file.stem} - {sheet_name}:"

        text += f"\n{lines[header_row - 1]}"
        count = 0
        for i in range(header_row, max_row):
            token_count = count_tokens(text, tokenizer) + count_tokens(lines[i], tokenizer)
            if token_count > max_len:
                chunks.append({
                    "text": f"(SL: {count}, Tổng: {max_row - header_row}) {text}",
                    "pages": [],
                })
                text = f"{file.stem} - {sheet_name}:\n{lines[header_row - 1]}"
                count = 0
            text += f"\n{lines[i]}"
            count += 1

        chunks.append({
            "text": f"(SL: {count}, Tổng: {max_row - header_row}) {text}",
            "pages": [],
        })

    return chunks


def run(model: str, src: Union[str, Path], overwrite: bool = True, to_console: bool = True, auto = True) -> List[dict]:
    """
    src có thể là:
    - đường dẫn local thật
    - hoặc path trong storage
    """
    local_path: Path | None = None
    parsed_path: Path | None = None

    try:
        src = str(src)
        storage = get_storage()

        body = storage.download(src).read()

        samples_dir = project_root() / "samples"
        samples_dir.mkdir(parents=True, exist_ok=True)

        local_path = samples_dir / os.path.basename(src)
        with open(local_path, "wb") as f:
            f.write(body)

        ext = local_path.suffix.lower()
        converter = _CONVERTERS.get(ext)

        if not converter:
            parsed_path = local_path
        else:
            if ext == ".docx":
                parsed_path = local_path.with_suffix(".pdf")
                if parsed_path.exists() and not overwrite:
                    raise FileExistsError(parsed_path)
                parsed_path = converter(local_path, parsed_path, to_console=to_console)
            else:
                parsed_path = local_path

        data = chunk_by_title(parsed_path) if auto else chunk_manually_doc(parsed_path)
        chunks = chunk_doc(data, model=model)
        return chunks

    finally:
        try:
            if parsed_path and parsed_path.exists() and parsed_path != local_path:
                os.remove(parsed_path)
        except Exception as e:
            log.warning("Cannot remove parsed_path %s: %s", parsed_path, e)

        try:
            if local_path and local_path.exists():
                os.remove(local_path)
        except Exception as e:
            log.warning("Cannot remove local_path %s: %s", local_path, e)