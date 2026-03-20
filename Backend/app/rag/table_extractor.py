"""
table_extractor.py — Extract bảng từ PDF và DOCX, render thành ảnh PNG.

Pipeline:
  PDF  → pdfplumber detect bảng → crop bbox → lưu PNG
  DOCX → python-docx đọc bảng  → render HTML → screenshot PNG (dùng imgkit)
         fallback: convert sang markdown text nếu không có imgkit
"""
import logging
import uuid
from pathlib import Path
from typing import Optional
import io

log = logging.getLogger(__name__)


# ── PDF: extract và crop bảng ────────────────────────────────

def extract_tables_from_pdf(pdf_path: Path, output_dir: Path) -> list[dict]:
    """
    Dùng pdfplumber detect bảng trong PDF.
    Crop từng bảng thành ảnh PNG, trả về list dict:
      {image_path, page, table_text, bbox}
    """
    try:
        import pdfplumber
        from PIL import Image
    except ImportError:
        log.error("Cần cài: pip install pdfplumber Pillow")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                tables = page.find_tables()
                if not tables:
                    continue

                # Render trang thành ảnh để crop
                page_img = page.to_image(resolution=150)
                pil_img  = page_img.original  # PIL Image

                for tbl_idx, table in enumerate(tables):
                    try:
                        # Lấy dữ liệu bảng dạng text
                        data = table.extract()
                        if not data or len(data) < 2:
                            continue

                        # Convert sang markdown text
                        md_rows = []
                        for i, row in enumerate(data):
                            cells = [str(c or "").strip() for c in row]
                            md_rows.append("| " + " | ".join(cells) + " |")
                            if i == 0:
                                md_rows.append("|" + "|".join(["---"] * len(cells)) + "|")
                        table_text = "\n".join(md_rows)

                        # Crop ảnh bảng từ trang
                        bbox = table.bbox  # (x0, y0, x1, y1) trong PDF coords
                        # Convert PDF coords → pixel coords
                        w_ratio = pil_img.width  / page.width
                        h_ratio = pil_img.height / page.height
                        px_bbox = (
                            int(bbox[0] * w_ratio),
                            int(bbox[1] * h_ratio),
                            int(bbox[2] * w_ratio),
                            int(bbox[3] * h_ratio),
                        )
                        cropped = pil_img.crop(px_bbox)

                        # Thêm padding
                        padded = Image.new("RGB",
                            (cropped.width + 20, cropped.height + 20),
                            (255, 255, 255))
                        padded.paste(cropped, (10, 10))

                        # Lưu PNG
                        img_name = f"table_{uuid.uuid4().hex[:8]}_p{page_num}_{tbl_idx}.png"
                        img_path = output_dir / img_name
                        padded.save(str(img_path), "PNG")

                        results.append({
                            "image_path": str(img_path),
                            "page":       page_num,
                            "table_text": table_text,
                            "type":       "table",
                        })
                        log.info(f"  🗃  Crop bảng trang {page_num}/{tbl_idx}: {img_name}")

                    except Exception as e:
                        log.warning(f"  Lỗi crop bảng trang {page_num}/{tbl_idx}: {e}")

    except Exception as e:
        log.error(f"Lỗi đọc PDF {pdf_path}: {e}")

    return results


# ── DOCX: extract bảng ───────────────────────────────────────

def extract_tables_from_docx(docx_path: Path, output_dir: Path) -> list[dict]:
    """
    Dùng python-docx đọc bảng trong DOCX.
    Render bảng thành ảnh PNG qua matplotlib (không cần imgkit/wkhtmltopdf).
    """
    try:
        import docx as python_docx
    except ImportError:
        log.error("Cần cài: pip install python-docx")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    try:
        doc = python_docx.Document(str(docx_path))

        for tbl_idx, table in enumerate(doc.tables):
            try:
                # Đọc dữ liệu bảng
                data = []
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    data.append(cells)

                if not data or len(data) < 2:
                    continue

                # Convert sang markdown text
                md_rows = []
                for i, row in enumerate(data):
                    md_rows.append("| " + " | ".join(row) + " |")
                    if i == 0:
                        md_rows.append("|" + "|".join(["---"] * len(row)) + "|")
                table_text = "\n".join(md_rows)

                # Render bảng thành ảnh PNG dùng matplotlib
                img_path = _render_table_to_png(data, output_dir, tbl_idx)

                if img_path:
                    results.append({
                        "image_path": str(img_path),
                        "page":       None,
                        "table_text": table_text,
                        "type":       "table",
                    })
                    log.info(f"  🗃  Render bảng DOCX {tbl_idx}: {Path(img_path).name}")

            except Exception as e:
                log.warning(f"  Lỗi xử lý bảng DOCX {tbl_idx}: {e}")

    except Exception as e:
        log.error(f"Lỗi đọc DOCX {docx_path}: {e}")

    return results


def _render_table_to_png(
    data: list[list[str]],
    output_dir: Path,
    idx: int,
) -> Optional[str]:
    """
    Render list[list[str]] thành ảnh PNG dùng matplotlib table.
    Không cần wkhtmltopdf hay browser.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        if not data:
            return None

        headers = data[0]
        rows    = data[1:]
        if not rows:
            return None

        n_cols = len(headers)
        n_rows = len(rows)

        # Tính kích thước figure tự động
        col_width  = max(2.0, min(3.5, 20 / n_cols))
        row_height = 0.5
        fig_w = col_width * n_cols + 0.5
        fig_h = row_height * (n_rows + 1) + 0.5

        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        ax.axis("off")

        tbl = ax.table(
            cellText=rows,
            colLabels=headers,
            loc="center",
            cellLoc="center",
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(9)
        tbl.scale(1, 1.4)

        # Style header
        for j in range(n_cols):
            cell = tbl[0, j]
            cell.set_facecolor("#2d3748")
            cell.set_text_props(color="white", fontweight="bold")

        # Style rows xen kẽ
        for i in range(1, n_rows + 1):
            color = "#f8f9fa" if i % 2 == 0 else "white"
            for j in range(n_cols):
                tbl[i, j].set_facecolor(color)

        plt.tight_layout(pad=0.5)

        img_name = f"table_docx_{uuid.uuid4().hex[:8]}_{idx}.png"
        img_path = output_dir / img_name
        plt.savefig(str(img_path), dpi=150, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        return str(img_path)

    except Exception as e:
        log.error(f"Lỗi render bảng thành PNG: {e}")
        return None


# ── Hàm chính gọi từ ingest.py ───────────────────────────────

def extract_all_tables(file_path: Path, output_dir: Path) -> list[dict]:
    """
    Auto-detect định dạng và extract tất cả bảng.
    Trả về list dict: {image_path, page, table_text, type}
    """
    ext = file_path.suffix.lower()

    if ext == ".pdf":
        return extract_tables_from_pdf(file_path, output_dir)
    elif ext == ".docx":
        return extract_tables_from_docx(file_path, output_dir)
    else:
        log.info(f"Định dạng {ext} không hỗ trợ extract bảng")
        return []