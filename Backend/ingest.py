"""
ingest.py — Phase 1 Ingest với hỗ trợ đầy đủ:
  ✓ Text chunking (existing pipeline)
  ✓ Hình ảnh từ PDF/DOCX (Gemini Vision mô tả)
  ✓ Bảng từ PDF/DOCX (crop/render → PNG → Gemini Vision mô tả)
"""
import argparse
import logging
import sys
import uuid
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from app.rag.doc_preprocessor import run as preprocess_doc
from app.rag.embedder import get_embeddings
from app.rag.qdrant_client_custom import qdrant_client
from app.rag.image_describer import describe_image
from app.rag.table_extractor import extract_all_tables
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}
DATA_DIR = ROOT / "data"
IMG_DIR = ROOT / "data" / "images"
IMG_DIR.mkdir(parents=True, exist_ok=True)


def _copy_to_static(src_path: str) -> str | None:
    """Copy ảnh/bảng vào thư mục static, trả về URL path."""
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

    # ── 1. Text chunks (pipeline cũ) ───────────────────────
    log.info("  [1/3] Parse text + ảnh...")
    try:
        text_chunks = preprocess_doc(
            model=settings.GEMINI_MODEL,
            src=str(file_path),
            overwrite=True,
            to_console=False,
        )
    except Exception as e:
        log.error(f"  Lỗi parse: {e}")
        text_chunks = []

    log.info(f"  → {len(text_chunks)} text chunks")

    # ── 2. Extract bảng riêng biệt ──────────────────────────
    log.info("  [2/3] Extract bảng...")
    tmp_dir = ROOT / "data" / "tmp_tables"
    table_items = extract_all_tables(file_path, tmp_dir)
    log.info(f"  → {len(table_items)} bảng tìm thấy")

    # ── 3. Enrich text chunks với ảnh ──────────────────────
    log.info("  [3/3] Mô tả ảnh + embed...")
    enriched = []

    # 3a. Text chunks + ảnh thường
    for chunk in text_chunks:
        image_urls = []
        image_descs = []

        for img_path in chunk.get("image_paths", []):
            if not img_path:
                continue
            url = _copy_to_static(img_path)
            if url:
                image_urls.append(url)

            desc = describe_image(img_path)
            if desc:
                image_descs.append(desc)

        embed_text = chunk["text"]
        if image_descs:
            embed_text += "\n\n" + "\n".join(f"[Hình ảnh: {d}]" for d in image_descs)

        enriched.append({
            "text": chunk["text"],
            "embed_text": embed_text,
            "pages": chunk.get("pages", []),
            "image_urls": image_urls,
            "image_descs": image_descs,
            "is_table": False,
        })

    # 3b. Bảng → tạo chunk riêng mỗi bảng
    for tbl in table_items:
        img_path = tbl["image_path"]
        url = _copy_to_static(img_path)

        desc = describe_image(img_path)
        if not desc:
            desc = "Bảng dữ liệu"

        embed_text = (
            f"[Bảng dữ liệu]\n{tbl['table_text']}\n\n"
            f"[Mô tả bảng: {desc}]"
        )

        page_info = [tbl["page"]] if tbl.get("page") else []

        enriched.append({
            "text": f"[Bảng] {desc}\n\n{tbl['table_text']}",
            "embed_text": embed_text,
            "pages": page_info,
            "image_urls": [url] if url else [],
            "image_descs": [desc],
            "is_table": True,
        })
        log.info(f"  🗃  Bảng chunk: {desc[:60]}...")

    # Xóa tmp
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not enriched:
        log.warning("  Không có chunk nào!")
        return 0

    log.info(f"  → Tổng {len(enriched)} chunks (text + bảng), bắt đầu embed...")

    # ── 4. Embed + upsert Qdrant ────────────────────────────
    batch_size = 16
    total = 0

    for i in range(0, len(enriched), batch_size):
        batch = enriched[i:i + batch_size]
        texts = [c["embed_text"] for c in batch]

        try:
            dense_vecs, sparse_vecs, _ = get_embeddings(texts)
        except Exception as e:
            log.error(f"  Embed lỗi batch {i // batch_size + 1}: {e}")
            continue

        vectors = []
        for j, chunk in enumerate(batch):
            sparse = sparse_vecs[j] or {}

            dense_vec = dense_vecs[j]
            if hasattr(dense_vec, "tolist"):
                dense_vec = dense_vec.tolist()

            dense_vec = [float(x) for x in dense_vec]

            vectors.append({
                "id": str(uuid.uuid4()),
                "vector": {
                    "dense": dense_vec,
                    "sparse": {
                        "indices": [int(k) for k in sparse.keys()],
                        "values": [float(v) for v in sparse.values()],
                    },
                },
                "payload": {
                    "content": chunk["text"],
                    "doc_id": doc_id,
                    "doc_name": file_path.name,
                    "pages": chunk["pages"],
                    "image_urls": chunk["image_urls"],
                    "image_descs": chunk["image_descs"],
                    "is_table": chunk["is_table"],
                    "created_at": datetime.utcnow().isoformat(),
                },
            })

        if qdrant_client.upsert_vectors(vectors):
            total += len(batch)
            log.info(f"  ✓ Batch {i // batch_size + 1}: {len(batch)} vectors")
        else:
            log.error(f"  ✗ Batch {i // batch_size + 1} thất bại")

    log.info(f"\n  ✅ {file_path.name}: {total} chunks vào Qdrant")
    log.info(f"     ({len(text_chunks)} text + {len(table_items)} bảng)")
    return total


def ingest_directory(directory: Path) -> None:
    files = [f for f in directory.rglob("*") if f.suffix.lower() in SUPPORTED]
    if not files:
        log.warning(f"Không có file nào trong {directory}")
        return

    log.info(f"Tìm thấy {len(files)} file")
    total = sum(ingest_file(f) for f in files)
    log.info(f"\n{'=' * 55}")
    log.info(f"✅ HOÀN TẤT: {len(files)} files, {total} chunks vào Qdrant")
    log.info(f"{'=' * 55}\nChạy uvicorn main:app --reload và chat thôi!")


def clear_collection() -> None:
    try:
        qdrant_client.client.delete_collection(settings.COLLECTION_NAME)
        qdrant_client.create_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)
        log.info("✓ Đã xóa và tạo lại collection rỗng")
    except Exception as e:
        log.error(f"Lỗi: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest data vào Qdrant")
    parser.add_argument("--file", type=str, help="1 file cụ thể")
    parser.add_argument("--dir", type=str, default=str(DATA_DIR))
    parser.add_argument("--clear", action="store_true", help="Xóa Qdrant rồi ingest lại")
    args = parser.parse_args()

    qdrant_client.create_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)

    if args.clear:
        clear_collection()

    if args.file:
        path = Path(args.file)
        if not path.exists():
            log.error(f"File không tồn tại: {path}")
            sys.exit(1)
        ingest_file(path)
    else:
        ingest_directory(Path(args.dir))