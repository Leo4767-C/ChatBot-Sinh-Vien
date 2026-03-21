"""
ingest.py — Ingest:
  ✓ Text chunks
  ✓ Ảnh/bảng trong text chunk
  ✓ Bảng riêng thành chunk riêng
  ✓ Copy ảnh vào static /images
  ✓ Upsert vào Qdrant với image_urls / image_descs
"""
import argparse
import logging
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from app.core.config import settings
from app.rag.doc_preprocessor import run as preprocess_doc
from app.rag.embedder import get_embeddings
from app.rag.image_describer import describe_image
from app.rag.qdrant_client_custom import qdrant_client
from app.rag.table_extractor import extract_all_tables

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}
DATA_DIR = ROOT / "data"
IMG_DIR = ROOT / "data" / "images"
IMG_DIR.mkdir(parents=True, exist_ok=True)


def _copy_to_static(src_path: str) -> str | None:
    src = Path(src_path)
    if not src.exists():
        return None

    ext = src.suffix.lower() or ".png"
    safe_name = f"{src.stem}_{uuid.uuid4().hex[:8]}{ext}"
    dest = IMG_DIR / safe_name
    shutil.copy2(src, dest)
    return f"/images/{safe_name}"


def ingest_file(file_path: Path, doc_id: str | None = None) -> int:
    log.info("\n%s", "=" * 55)
    log.info("📄 Đang xử lý: %s", file_path.name)
    log.info("%s", "=" * 55)

    if not doc_id:
        doc_id = str(uuid.uuid4())

    log.info("  [1/3] Parse text + ảnh trong chunk...")
    try:
        text_chunks = preprocess_doc(
            model=settings.GEMINI_MODEL,
            src=str(file_path),
            overwrite=True,
            to_console=False,
        )
    except Exception as e:
        log.exception("  Lỗi parse: %s", e)
        text_chunks = []

    log.info("  → %s text chunks", len(text_chunks))

    log.info("  [2/3] Extract bảng riêng...")
    tmp_dir = ROOT / "data" / "tmp_tables"
    table_items = extract_all_tables(file_path, tmp_dir)
    log.info("  → %s bảng tìm thấy", len(table_items))

    log.info("  [3/3] Mô tả ảnh + embed...")
    enriched = []

    # text chunks
    for chunk in text_chunks:
        image_urls = []
        image_descs = []

        for img_path in chunk.get("image_paths", []):
            if not img_path:
                continue

            url = _copy_to_static(img_path)
            if url:
                image_urls.append(url)

            try:
                desc = describe_image(img_path)
            except Exception:
                desc = None

            if desc:
                image_descs.append(desc)

        embed_text = chunk.get("text", "") or ""
        if image_descs:
            embed_text += "\n\n" + "\n".join(f"[Hình ảnh: {d}]" for d in image_descs)

        enriched.append({
            "text": chunk.get("text", ""),
            "embed_text": embed_text,
            "pages": chunk.get("pages", []),
            "image_urls": image_urls,
            "image_descs": image_descs,
            "is_table": False,
        })

    # bảng riêng
    for tbl in table_items:
        img_path = tbl.get("image_path")
        if not img_path:
            continue

        url = _copy_to_static(img_path)

        try:
            desc = describe_image(img_path)
        except Exception:
            desc = None

        if not desc:
            desc = "Bảng dữ liệu"

        table_text = (tbl.get("table_text") or "").strip()
        page_value = tbl.get("page")
        page_info = [page_value] if page_value else []

        embed_text = f"[Bảng dữ liệu]\n{table_text}\n\n[Mô tả bảng: {desc}]"

        enriched.append({
            "text": f"[Bảng] {desc}\n\n{table_text}",
            "embed_text": embed_text,
            "pages": page_info,
            "image_urls": [url] if url else [],
            "image_descs": [desc],
            "is_table": True,
        })

        log.info("  🗃  Bảng chunk: %s...", desc[:60])

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not enriched:
        log.warning("  Không có chunk nào!")
        return 0

    log.info("  → Tổng %s chunks (text + bảng), bắt đầu embed...", len(enriched))

    batch_size = 16
    total = 0

    for i in range(0, len(enriched), batch_size):
        batch = enriched[i:i + batch_size]
        texts = [c["embed_text"] for c in batch]

        try:
            dense_vecs, sparse_vecs, _ = get_embeddings(texts)
        except Exception as e:
            log.exception("  Embed lỗi batch %s: %s", i // batch_size + 1, e)
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
                    "image_urls": [u for u in chunk["image_urls"] if u],
                    "image_descs": chunk["image_descs"],
                    "is_table": chunk["is_table"],
                    "created_at": datetime.utcnow().isoformat(),
                },
            })

        success_count = qdrant_client.upsert_vectors(vectors)
        if success_count:
            total += success_count
            log.info("  ✓ Batch %s: %s vectors", i // batch_size + 1, success_count)
        else:
            log.error("  ✗ Batch %s thất bại", i // batch_size + 1)

    log.info("\n  ✅ %s: %s chunks vào Qdrant", file_path.name, total)
    log.info("     (%s text + %s bảng)", len(text_chunks), len(table_items))
    return total


def ingest_directory(directory: Path) -> None:
    files = [f for f in directory.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED]
    if not files:
        log.warning("Không có file nào trong %s", directory)
        return

    log.info("Tìm thấy %s file", len(files))
    total = sum(ingest_file(f) for f in files)
    log.info("\n%s", "=" * 55)
    log.info("✅ HOÀN TẤT: %s files, %s chunks vào Qdrant", len(files), total)
    log.info("%s", "=" * 55)
    log.info("Chạy uvicorn main:app --reload và chat thôi!")


def clear_collection() -> None:
    try:
        qdrant_client.recreate_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)
        log.info("✓ Đã xóa và tạo lại collection hybrid")
    except Exception as e:
        log.error("Lỗi: %s", e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest data vào Qdrant")
    parser.add_argument("--file", type=str, help="1 file cụ thể")
    parser.add_argument("--dir", type=str, default=str(DATA_DIR))
    parser.add_argument("--clear", action="store_true", help="Xóa Qdrant rồi ingest lại")
    args = parser.parse_args()

    if args.clear:
        qdrant_client.recreate_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)
    else:
        qdrant_client.create_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)

    if args.file:
        path = Path(args.file)
        if not path.exists():
            log.error("File không tồn tại: %s", path)
            sys.exit(1)
        ingest_file(path)
    else:
        ingest_directory(Path(args.dir))