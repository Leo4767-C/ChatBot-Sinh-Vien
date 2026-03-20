import copy
from pathlib import Path
from typing import Union
import logging, datetime

from openpyxl.reader.excel import load_workbook

from app.rag.chunker import get_tokenizer, estimate_max_tokens_per_chunk
from app.rag.restructure_titles import chunk_by_title
from app.rag.converters import DocumentConverter, convert_to_pdf, excel_to_csv
from app.core.config import settings

import re
from typing import Dict, Any, List
import tiktoken
import os

from app.storage.helper import StorageHelper
from app.storage.storage_service import get_storage
from app.utils.helpers import project_root

os.environ["CUDA_VISIBLE_DEVICES"] = settings.CUDA_VISIBLE_DEVICES

log = logging.getLogger(__name__)

# ---------- Tách câu rất gọn ----------
# _SENT_RE = re.compile(r'''(?x) (?<!\b\d) (?<!\b[a-zA-Z]) (?<=[.!?])\s+ | \n+ ''')
# (?<!\b\d)       : Lookbehind âm - Không cắt nếu trước dấu chấm là 1 chữ số (vd: 1. 2.)
# (?<!\b\d\d)     : Lookbehind âm - Không cắt nếu trước dấu chấm là 2 chữ số (vd: 10. 12. 99.)
# (?<!\b[a-zA-Z]) : Lookbehind âm - Không cắt nếu trước dấu chấm là 1 ký tự (vd: a. b. C.)
# (?<=[.!?])      : Lookbehind dương - Chỉ cắt nếu ký tự trước đó là dấu câu (. ! ?)
# \s+             : Khớp với dấu cách hoặc xuống dòng ngay sau dấu câu
_SENT_RE = re.compile(r'(?<!\b\d)(?<!\b\d\d)(?<!\b[a-zA-Z])(?<=[.!?])\s+')

_CONVERTERS: Dict[str, DocumentConverter] = {
    # ".pdf": pdf_to_markdown,
    ".docx": convert_to_pdf,
    # ".xls": excel_to_csv,
    # ".xlsx": excel_to_csv,
}

storage_helper = StorageHelper()

def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENT_RE.split(text.strip()) if s.strip()]


def count_tokens(text: str, tokenizer) -> int:
    return len(tokenizer.encode(text))


# ---------- Hàm chính ----------
def chunk_doc(doc: Dict[str, Any], model: str) -> List[dict]:
    from app.llm.llm_service import llm_client

    path: List[str] = []  # stack tiêu đề
    # buffer mới: lưu trữ dữ liệu của chunk đang xây dựng
    current_chunk: Dict[str, Any] = {
        "text": "",
        "pages": set(),  # Dùng set để lưu trữ và tự động loại bỏ trùng lặp
        "image_paths": set(),  # Dùng set để lưu trữ và tự động loại bỏ trùng lặp
    }
    chunks: List[Dict[str, Any]] = []

    def reset_buffer():
        nonlocal current_chunk
        current_chunk = {
            "text": "",
            "pages": set(),
            "image_paths": set(),
        }

    def header() -> str:
        """Ghép full đường dẫn tiêu đề: A.\n B.\n C."""
        return ".\n".join(path)

    def flush() -> None:
        """Kết thúc chunk hiện tại (nếu có)."""
        nonlocal current_chunk
        text = current_chunk["text"].strip()
        if text:
            chunk = {
                "text": text,
                "pages": sorted(list(current_chunk["pages"])),
                "image_paths": list(current_chunk["image_paths"]),
            }
            chunks.append(chunk)
            log.debug(f"Chunk flushed (len: {len(text)})")
            # Reset buffer sau khi flush
            reset_buffer()
        else:
            log.info("⚠️ Flush called but buffer was empty")

    def ensure_header() -> None:
        """Khi buffer rỗng, bắt đầu bằng header mới."""
        nonlocal current_chunk
        if not current_chunk["text"]:
            current_chunk["text"] = header()

    def add_piece(txt: str, pages: List[int], image_paths: List[str]) -> None:
        """Ghép 1 câu hoặc 1 tiêu đề; tự flush nếu vượt max_len."""
        nonlocal current_chunk
        # 1. Thêm vào buffer (text và metadata)
        ensure_header()
        connector = "\n" if current_chunk["text"] and not current_chunk["text"].endswith("\n") else ""
        piece = connector + txt

        token_count = llm_client.count_tokens(model=model, content=current_chunk["text"]) + llm_client.count_tokens(model=model, content=piece)
        if token_count > settings.CHUNK_SIZE:
            log.info(f"Flushing because token count exceeded, token count = {token_count}, max_len = {settings.CHUNK_SIZE}")
            current_chunk["text"] += piece[:settings.OVERLAP]  # Thêm overlap trước khi flush
            flush()
            ensure_header()
            # FIX: sau flush KHÔNG thêm piece lại — ensure_header đã đặt header mới,
            # piece sẽ được append bình thường ở dưới NHƯNG không nên thêm lại toàn bộ piece
            # vì overlap đã được xử lý. Reset piece về phần sau overlap.
            piece = piece[settings.OVERLAP:]
        # 2. Cập nhật buffer
        current_chunk["text"] += piece
        current_chunk["pages"].update(pages)
        current_chunk["image_paths"].update(image_paths)

    def dfs(node: Dict[str, Any]) -> None:
        nonlocal current_chunk

        if not isinstance(node, dict):
            log.warning(f"Invalid node encountered (not a dict): {node}")
            return

        # Lấy metadata từ node hiện tại
        node_pages = node.get("pages", [])
        node_images = node.get("image_paths", [])

        # 1) Vào node
        node_title = node.get("title", "").strip()
        path.append(node_title)

        if current_chunk["text"]:
            add_piece(node["title"].strip() + ".", node_pages, node_images)

        # 2) Content
        # Thêm toàn bộ metadata của node vào buffer ngay trước khi xử lý nội dung
        current_chunk["pages"].update(node_pages)
        current_chunk["image_paths"].update(node_images)
        for sent in split_sentences(node.get("content", "")):
            add_piece(sent, node_pages, node_images)

        # 3) Children – cố gắng gộp được càng nhiều node càng tốt
        for i, child in enumerate(node.get("children", [])):
            # Sao lưu trạng thái hiện tại (bao gồm cả metadata)
            backup_chunk = copy.deepcopy(current_chunk)
            backup_chunks = chunks[:]
            backup_path = path[:]

            dfs(child)

            # nếu flush() đã được gọi trong quá trình dfs
            if len(chunks) > len(backup_chunks):  # flush happened
                current_chunk.update(backup_chunk)
                chunks[:] = backup_chunks
                path[:] = backup_path
                flush()
                dfs(child)

        path.pop()

    dfs(doc)
    flush()  # Đảm bảo flush phần cuối cùng nếu còn dữ liệu
    return chunks


def chunk_excel(file: Path, tokenizer: tiktoken.Encoding, max_len: int = 600) -> list[dict]:
    def detect_excel_header(ws, scan=5):
        """
        Detects the header row in an Excel worksheet.
        Args:
            ws (openpyxl.worksheet.worksheet.Worksheet): The worksheet to scan.
            scan (int): The number of rows to scan for the header.
        Returns:
            int: The row number of the header.
        """
        scores = []

        for r in range(1, scan + 1):
            row = ws[r]

            bold_count = sum(
                1 for cell in row if cell.font and cell.font.bold
            )
            text_count = sum(
                1 for cell in row if isinstance(cell.value, str)
            )
            number_count = sum(
                1 for cell in row if isinstance(cell.value, (int, float))
            )

            score = bold_count * 3 + text_count * 2 - number_count
            scores.append((r, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[0][0]

    def get_real_data_range(ws):
        """
        Get the range of the real data in a worksheet.
        Args:
            ws: The worksheet to scan.
        Returns:
            tuple(max_row, max_col): A tuple containing the start and end row numbers of the real data.
        """
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

    def read_ws_data(ws, max_row, max_col, header_row=1):
        lines = []

        for r in range(1, max_row + 1):
            row = ws[r]
            processed_cells = []

            for c in range(1, max_col + 1):
                cell = row[c - 1].value

                # Convert
                if cell is None:
                    cell_str = ""
                else:
                    cell_str = str(cell)

                # Nếu chứa dấu phẩy, newline, hoặc dấu "
                if ("," in cell_str) or ("\n" in cell_str) or ('"' in cell_str):
                    cell_str = cell_str.replace('"', '""')
                    cell_str = f'"{cell_str}"'

                processed_cells.append(cell_str)

            line = ",".join(processed_cells)
            lines.append(line)

        return lines

    chunks = []
    metadata = ""

    wb = load_workbook(file)
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        header_row = detect_excel_header(ws)
        max_row, max_col = get_real_data_range(ws)
        lines = read_ws_data(ws, max_row, max_col, header_row)

        text = f"{file.stem} - {sheet_name}:"

        # Xử lý data nằm trên header (khi header_row > 1)
        if header_row > 1:
            log.info(f"Sheet {sheet_name} - Header row {header_row}")
            for i in range(0, header_row - 1):  # lines[0..header_row-2] là các dòng trước header (0-indexed)
                token_count = count_tokens(text, tokenizer) + count_tokens(lines[i], tokenizer)
                if token_count > max_len:
                    log.info(f"Flushing because token count exceeded, token count = {token_count}, max_len = {max_len}")
                    chunks.append({"text": text})
                    text = f"{file.stem} - {sheet_name}:"
                text += f"\n{lines[i]}"
            # fallback cho chunk cuối
            chunks.append({"text": text})
            text = f"{file.stem} - {sheet_name}:"

        # Xử lý các dòng dữ liệu thường
        text += f"\n{lines[header_row - 1]}" # Nối dòng header
        count = 0
        for i in range(header_row, max_row):
            token_count = count_tokens(text, tokenizer) + count_tokens(lines[i], tokenizer)
            if token_count > max_len:
                log.info(f"Flushing because token count exceeded, token count = {token_count}, max_len = {max_len}")
                chunks.append({"text": f"(SL: {count}, Tổng: {max_row - header_row}) {text}"})
                text = f"{file.stem} - {sheet_name}:\n{lines[header_row - 1]}"
                count = 0
            text += f"\n{lines[i]}"
            count += 1
        # fallback cho chunk cuối
        chunks.append({"text": f"(SL: {count}, Tổng: {max_row - header_row}) {text}"})

    return chunks


def run(model: str, src: Union[str, Path], overwrite: bool = True, to_console: bool = True) -> List[dict]:
    try:
        body = get_storage().download(src).read()

        samples_dir = project_root() / "samples"
        samples_dir.mkdir(parents=True, exist_ok=True)
        local_path = samples_dir / os.path.basename(src)

        with open(local_path, "wb") as f:
            f.write(body)

        log.info(f"Tải xuống và lưu thành công tại: {local_path}")
    except Exception as e:
        log.error("Error: %s", e)
        raise

    # tokenizer = get_tokenizer(model_name)
    # max_len_token = estimate_max_tokens_per_chunk(model, reserve_tokens=reserve_tokens)

    ext = local_path.suffix.lower()
    converter = _CONVERTERS.get(ext)
    if not converter:
        log.info(f"File not use converter: {src}")
        # if ext == '.xlsx' or ext == '.xls':
        #     return chunk_excel(local_path, tokenizer, max_len=max_len_token)
        dest = local_path
    else:
        match ext:
            case ".docx":
                dest = local_path.with_suffix(".pdf")
                if dest.exists() and not overwrite:
                    raise FileExistsError(dest)
                dest = converter(local_path, dest, to_console=to_console)
                os.remove(local_path)

    # TODO: Xử lý file excel, pptx, txt

    data = chunk_by_title(dest)
    os.remove(dest)

    # todo: max_len
    return chunk_doc(data, model=model)