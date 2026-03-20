# Đọc & chuẩn hóa file từ local/S3
# todo

import os
from typing import Optional
from collections import Counter
import docx2txt
import pdfplumber
import re

SUPPORTED_EXTENSTIONS = [".pdf", ".docx", ".txt"]


def load_file(file_path: str) -> Optional[str]:
    """
        Đọc nội dung văn bản từ file PDF, DOCX, hoặc TXT.

        Args:
            file_path (str): Đường dẫn đến file.

        Returns:
            str | None: Nội dung văn bản hoặc None nếu không hỗ trợ.
        """
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_EXTENSTIONS:
        raise ValueError(f"File type {ext} is not supported.")

    try:
        if ext == ".pdf":
            return load_pdf(file_path)
        elif ext == ".docx":
            return load_docx(file_path)
        elif ext == ".txt":
            return load_txt(file_path)
    except Exception as e:
        print(f"[load_file] Error reading {file_path}: {e}")


def load_pdf(file_path: str) -> str:
    # Bước 1: Trích xuất text từng trang
    pages = extract_pages_from_pdf(file_path)

    # Bước 2: Phát hiện header/footer và loại bỏ
    header, footer = detect_common_headers_footers(pages)

    # Bước 3: Làm sạch nội dung văn bản
    cleaned_pages = remove_headers_footers(pages, header, footer)

    # Làm sạch và in ra kết quả
    final_text = clean_text(cleaned_pages)

    return final_text


def load_docx(file_path: str) -> str:
    raw_text = docx2txt.process(file_path)
    lines = raw_text.splitlines()
    print(lines)
    return clean_text([lines])  # Gói lại thành 1 "trang"


def load_txt(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read().strip()

# ---------------------------------- PROCESSING FILE -------------------------------------------------

def extract_pages_from_pdf(file_path):
    page_texts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            lines = text.splitlines() if text else []
            page_texts.append(lines)

    return page_texts

def detect_common_headers_footers(pages):
    headers = []
    footers = []
    for lines in pages:
        if len(lines) >= 2:
            headers.append(lines[0].strip())
            footers.append(lines[-1].strip())

    common_header = Counter(headers).most_common(1)[0][0] if headers else ''
    common_footer = Counter(footers).most_common(1)[0][0] if footers else ''
    return common_header, common_footer

def remove_headers_footers(pages, header, footer):
    cleaned_pages = []
    for lines in pages:
        if lines and lines[0].strip() == header:
            lines = lines[1:]
        if lines and lines[-1].strip() == footer:
            lines = lines[:-1]
        cleaned_pages.append(lines)
    return cleaned_pages

def clean_text(pages):
    all_text = []

    for lines in pages:
        for line in lines:
            line = line.strip()

            # Loại bỏ các chuỗi "....." dài
            line = re.sub(r"\.{4,}", "", line)

            # Loại bỏ các dòng chứa chỉ số trang (ví dụ: Page 1, Trang 2, Trang số 3)
            if re.search(r"(page|trang)\s*\d+", line, re.IGNORECASE):
                continue

            if re.fullmatch(r"[-–—]*\s*\d+\s*[-–—/\\]*", line.strip()):
                continue

            if line:
                all_text.append(line)

    return "\n".join(all_text)

def table_to_key_value_text(table):
    result = []
    for row in table:
        # row là list cell, giả sử mỗi row có cột Key và Value
        # ví dụ: ["Tên thuốc", "Paracetamol"]
        if len(row) >= 2:
            key = row[0].strip() if row[0] else ""
            value = row[1].strip() if row[1] else ""
            if key and value:
                result.append(f"{key}: {value}")
        else:
            # Nếu row chỉ có 1 cell hoặc trống, có thể bỏ qua hoặc xử lý khác
            continue
    return "\n".join(result)