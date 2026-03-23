"""
table_extractor.py — Extract bảng từ PDF và DOCX, chỉ giữ text, không render ảnh.
"""
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def extract_tables_from_pdf(pdf_path: Path, output_dir: Path | None = None) -> list[dict]:
    """
    Dùng pdfplumber detect bảng trong PDF.
    Trả về list dict:
      {page, table_text, type}
    """
    try:
        import pdfplumber
    except ImportError:
        log.error("Cần cài: pip install pdfplumber")
        return []

    results = []

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                tables = page.find_tables()
                if not tables:
                    continue

                for tbl_idx, table in enumerate(tables):
                    try:
                        data = table.extract()
                        if not data or len(data) < 2:
                            continue

                        md_rows = []
                        for i, row in enumerate(data):
                            cells = [str(c or "").strip() for c in row]
                            md_rows.append("| " + " | ".join(cells) + " |")
                            if i == 0:
                                md_rows.append("|" + "|".join(["---"] * len(cells)) + "|")
                        table_text = "\n".join(md_rows)

                        results.append({
                            "page": page_num,
                            "table_text": table_text,
                            "type": "table",
                        })
                        log.info(f"  🗃  Extract bảng PDF trang {page_num}/{tbl_idx}")

                    except Exception as e:
                        log.warning(f"  Lỗi extract bảng trang {page_num}/{tbl_idx}: {e}")

    except Exception as e:
        log.error(f"Lỗi đọc PDF {pdf_path}: {e}")

    return results


def extract_tables_from_docx(docx_path: Path, output_dir: Path | None = None) -> list[dict]:
    """
    Dùng python-docx đọc bảng trong DOCX.
    Chỉ trả text bảng, không render ảnh PNG.
    """
    try:
        import docx as python_docx
    except ImportError:
        log.error("Cần cài: pip install python-docx")
        return []

    results = []

    try:
        doc = python_docx.Document(str(docx_path))

        for tbl_idx, table in enumerate(doc.tables):
            try:
                data = []
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    data.append(cells)

                if not data or len(data) < 2:
                    continue

                md_rows = []
                for i, row in enumerate(data):
                    md_rows.append("| " + " | ".join(row) + " |")
                    if i == 0:
                        md_rows.append("|" + "|".join(["---"] * len(row)) + "|")
                table_text = "\n".join(md_rows)

                results.append({
                    "page": None,
                    "table_text": table_text,
                    "type": "table",
                })
                log.info(f"  🗃  Extract bảng DOCX {tbl_idx}")

            except Exception as e:
                log.warning(f"  Lỗi xử lý bảng DOCX {tbl_idx}: {e}")

    except Exception as e:
        log.error(f"Lỗi đọc DOCX {docx_path}: {e}")

    return results


def extract_all_tables(file_path: Path, output_dir: Path | None = None) -> list[dict]:
    """
    Auto-detect định dạng và extract tất cả bảng.
    Trả về list dict: {page, table_text, type}
    """
    ext = file_path.suffix.lower()

    if ext == ".pdf":
        return extract_tables_from_pdf(file_path, output_dir)
    elif ext == ".docx":
        return extract_tables_from_docx(file_path, output_dir)
    else:
        log.info(f"Định dạng {ext} không hỗ trợ extract bảng")
        return []