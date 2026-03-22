import argparse
import logging
import sys
import uuid
import shutil
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

# Sử dụng thẳng Gemini và PIL cho ảnh, vứt bỏ Tesseract/Unstructured
import google.generativeai as genai
from PIL import Image

from app.rag.doc_preprocessor import run as preprocess_doc
from app.rag.embedder import get_embeddings
from app.rag.qdrant_client_custom import qdrant_client
from app.rag.image_describer import describe_image
from app.rag.table_extractor import extract_all_tables
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".jpg", ".jpeg", ".png", ".webp"}
DATA_DIR = ROOT / "data"
IMG_DIR = ROOT / "data" / "images"
IMG_DIR.mkdir(parents=True, exist_ok=True)

# Cấu hình Gemini API
genai.configure(api_key=settings.EFFECTIVE_GEMINI_API_KEY)


def _copy_to_static(src_path: str) -> str | None:
    src = Path(src_path)
    if not src.exists():
        return None
    dest = IMG_DIR / src.name
    if not dest.exists():
        shutil.copy2(src, dest)
    return f"/images/{src.name}"


def ingest_file(file_path: Path, doc_id: str | None = None) -> int:
    log.info(f"\n{'=' * 55}")
    log.info(f"📄 Đang xử lý: {file_path.name}")
    log.info(f"{'=' * 55}")

    if not doc_id:
        doc_id = str(uuid.uuid4())

    enriched = []
    ext = file_path.suffix.lower()

    # ── 1. NẾU LÀ ẢNH (DÙNG GEMINI VISION ĐỂ ĐỌC CHỮ & BẢNG BIỂU) ──
    if ext in [".jpg", ".jpeg", ".png", ".webp"]:
        log.info("  [Gemini Vision] Đang phân tích hình ảnh và bảng biểu...")
        try:
            img_pil = Image.open(file_path).convert("RGB")
            model = genai.GenerativeModel(model_name=settings.GEMINI_MODEL)
            
            # Prompt tối ưu hóa cho NCKH (Nhận diện bảng)
            prompt = (
                "Hãy trích xuất toàn bộ văn bản trong ảnh này. "
                "Nếu trong ảnh có BẢNG BIỂU (ví dụ bảng điểm, bảng số liệu), "
                "BẮT BUỘC phải trình bày lại dưới dạng bảng Markdown chính xác từng hàng và cột. "
                "Nếu là sơ đồ, hãy giải thích chi tiết."
            )
            
            res = model.generate_content([prompt, img_pil])
            text_content = res.text
            
            if text_content and text_content.strip():
                url = _copy_to_static(str(file_path))
                enriched.append({
                    "text": f"[Dữ liệu bóc tách từ ảnh: {file_path.name}]\n{text_content}",
                    "embed_text": text_content,
                    "pages": [1],
                    "image_urls": [url] if url else [],
                    "image_descs": ["Ảnh gốc phân tích"],
                    "is_table": True if "|" in text_content else False, # Nhận diện nhanh Markdown table
                })
                log.info(f"  → Phân tích thành công! Thu được {len(text_content)} ký tự.")
            else:
                log.warning("  → Gemini không tìm thấy thông tin hữu ích trong ảnh này.")
        except Exception as e:
            log.error(f"  Lỗi Gemini Vision: {e}")

    # ── 2. NẾU LÀ FILE VĂN BẢN (PIPELINE CŨ) ──
    else:
        log.info("  [1/3] Parse text + ảnh...")
        try:
            text_chunks = preprocess_doc(
                model=settings.GEMINI_MODEL, src=str(file_path), overwrite=True, to_console=False
            )
        except Exception as e:
            log.error(f"  Lỗi parse: {e}")
            text_chunks = []

        # ... (Giữ nguyên logic extract bảng và enrich cũ của bạn) ...
        tmp_dir = ROOT / "data" / "tmp_tables"
        table_items = extract_all_tables(file_path, tmp_dir)
        
        for chunk in text_chunks:
            image_urls, image_descs = [], []
            for img_path in chunk.get("image_paths", []):
                if not img_path: continue
                url = _copy_to_static(img_path)
                if url: image_urls.append(url)
                desc = describe_image(img_path)
                if desc: image_descs.append(desc)

            embed_text = chunk["text"]
            if image_descs: embed_text += "\n\n" + "\n".join(f"[Hình ảnh: {d}]" for d in image_descs)
            enriched.append({
                "text": chunk["text"], "embed_text": embed_text,
                "pages": chunk.get("pages", []), "image_urls": image_urls,
                "image_descs": image_descs, "is_table": False,
            })

        for tbl in table_items:
            img_path = tbl["image_path"]
            url = _copy_to_static(img_path)
            desc = describe_image(img_path) or "Bảng dữ liệu"
            embed_text = f"[Bảng dữ liệu]\n{tbl['table_text']}\n\n[Mô tả bảng: {desc}]"
            enriched.append({
                "text": f"[Bảng] {desc}\n\n{tbl['table_text']}", "embed_text": embed_text,
                "pages": [tbl["page"]] if tbl.get("page") else [],
                "image_urls": [url] if url else [], "image_descs": [desc], "is_table": True,
            })
            
        if tmp_dir.exists(): shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── 3. EMBED VÀ LƯU VÀO QDRANT ──
    if not enriched:
        log.warning("  Không có chunk nào để lưu từ file này!")
        return 0

    batch_size = 16
    total = 0

    for i in range(0, len(enriched), batch_size):
        batch = enriched[i:i + batch_size]
        texts = [c["embed_text"] for c in batch]

        try:
            dense_vecs, sparse_vecs, _ = get_embeddings(texts)
        except Exception as e:
            log.error(f"  Embed lỗi batch: {e}")
            continue

        vectors = []
        for j, chunk in enumerate(batch):
            sparse = sparse_vecs[j] or {}
            dense_vec = dense_vecs[j].tolist() if hasattr(dense_vecs[j], "tolist") else dense_vecs[j]
            
            vectors.append({
                "id": str(uuid.uuid4()),
                "vector": {"dense": [float(x) for x in dense_vec], "sparse": {"indices": [int(k) for k in sparse.keys()], "values": [float(v) for v in sparse.values()]}},
                "payload": {
                    "content": chunk["text"], "doc_id": doc_id, "doc_name": file_path.name,
                    "pages": chunk["pages"], "image_urls": chunk["image_urls"],
                    "image_descs": chunk["image_descs"], "is_table": chunk["is_table"],
                    "created_at": datetime.utcnow().isoformat(),
                },
            })

        if qdrant_client.upsert_vectors(vectors):
            total += len(batch)
        else:
            log.error("  ✗ Lỗi lưu vào Qdrant")

    log.info(f"  ✅ Thành công: Lưu {total} chunks vào Qdrant")
    return total

def ingest_directory(directory: Path) -> None:
    files = [f for f in directory.rglob("*") if f.suffix.lower() in SUPPORTED]
    if not files: return
    total = sum(ingest_file(f) for f in files)
    log.info(f"\n✅ HOÀN TẤT: {len(files)} files, {total} chunks vào Qdrant")

from qdrant_client.models import VectorParams, Distance, SparseVectorParams

def init_collection(clear=False):
    if clear:
        try:
            qdrant_client.client.delete_collection(settings.COLLECTION_NAME)
            log.info("✓ Đã xóa collection cũ trên đám mây")
        except Exception:
            pass
    
    try:
        # Check xem collection đã tồn tại chưa, chưa có thì mới tạo
        if clear or not qdrant_client.client.collection_exists(settings.COLLECTION_NAME):
            qdrant_client.client.create_collection(
                collection_name=settings.COLLECTION_NAME,
                vectors_config={
                    "dense": VectorParams(size=settings.EMBEDDING_VECTOR_SIZE, distance=Distance.COSINE)
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams()
                }
            )
            log.info("✓ Đã khởi tạo collection hỗ trợ Dense & Sparse vector")
    except Exception as e:
        log.error(f"Lỗi tạo collection: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest data vào Qdrant")
    parser.add_argument("--file", type=str, help="1 file cụ thể")
    parser.add_argument("--dir", type=str, default=str(DATA_DIR))
    parser.add_argument("--clear", action="store_true", help="Xóa Qdrant rồi ingest lại")
    args = parser.parse_args()

    # Khởi tạo collection với cấu hình chuẩn
    init_collection(clear=args.clear)

    if args.file:
        path = Path(args.file)
        if not path.exists():
            log.error(f"File không tồn tại: {path}")
            sys.exit(1)
        ingest_file(path)
    else:
        ingest_directory(Path(args.dir))