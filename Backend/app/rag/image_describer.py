"""
Image Describer — dùng Gemini Vision để mô tả ảnh được crop từ PDF.
Kết quả mô tả được embed cùng chunk text vào Qdrant.
"""
import base64
import logging
from pathlib import Path

import google.generativeai as genai
from app.core.config import settings

log = logging.getLogger(__name__)

genai.configure(api_key=settings.GEMINI_API_KEY)


def describe_image(image_path: str | Path) -> str | None:
    """
    Gửi ảnh cho Gemini Vision để lấy mô tả chi tiết bằng tiếng Việt.
    Trả về chuỗi mô tả hoặc None nếu lỗi.
    """
    path = Path(image_path)
    if not path.exists():
        log.warning(f"Ảnh không tồn tại: {path}")
        return None

    try:
        # Đọc ảnh và encode base64
        image_data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")

        # Xác định mime type
        suffix = path.suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp"}
        mime_type = mime_map.get(suffix, "image/jpeg")

        model = genai.GenerativeModel(model_name=settings.GEMINI_MODEL)

        response = model.generate_content([
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": image_data,
                }
            },
            """Hãy mô tả chi tiết hình ảnh này bằng tiếng Việt.
Tập trung vào:
- Nội dung chính của hình (biểu đồ, sơ đồ, bảng số liệu, hình minh họa...)
- Các con số, nhãn, tiêu đề nếu có
- Ý nghĩa khoa học/học thuật của hình nếu có thể nhận biết
Mô tả ngắn gọn trong 2-4 câu."""
        ])

        description = response.text.strip()
        log.info(f"Đã mô tả ảnh {path.name}: {description[:80]}...")
        return description

    except Exception as e:
        log.error(f"Lỗi mô tả ảnh {path}: {e}")
        return None


def describe_images_batch(image_paths: list[str]) -> dict[str, str]:
    """
    Mô tả nhiều ảnh, trả về dict {path: description}.
    """
    results = {}
    for p in image_paths:
        desc = describe_image(p)
        if desc:
            results[p] = desc
    return results