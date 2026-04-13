"""
ingest.py — Ingest:
  ✓ Chỉ ingest file mới
  ✓ Skip file cũ không đổi
  ✓ Nếu file cùng tên nhưng nội dung đổi -> xóa dữ liệu cũ của file đó rồi ingest lại
  ✓ Không dùng ảnh từ data, chỉ giữ text + bảng text-only
"""
import argparse
import hashlib
import logging
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from qdrant_client.models import Filter, FieldCondition, MatchValue

from app.core.config import settings
from app.rag.doc_preprocessor import run as preprocess_doc
from app.rag.embedder import get_embeddings
from app.rag.qdrant_client_custom import qdrant_client
from app.rag.table_extractor import extract_all_tables

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}
DATA_DIR = ROOT / "data"


def sha256_file(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_existing_doc_info(doc_name: str):
    """
    Tìm dữ liệu đã ingest của 1 file theo doc_name.
    Trả về:
      - None nếu chưa có
      - dict gồm doc_id, doc_name, file_hash nếu đã có
    """
    try:
        client = qdrant_client.client
        collection_name = settings.COLLECTION_NAME

        points, _ = client.scroll(
            collection_name=collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="doc_name",
                        match=MatchValue(value=doc_name)
                    )
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )

        if not points:
            return None

        payload = points[0].payload or {}
        return {
            "doc_id": payload.get("doc_id"),
            "doc_name": payload.get("doc_name"),
            "file_hash": payload.get("file_hash"),
        }
    except Exception as e:
        log.warning("Không kiểm tra được doc cũ trong Qdrant cho %s: %s", doc_name, e)
        return None


def delete_doc_by_name(doc_name: str) -> bool:
    """
    Xóa toàn bộ chunks của 1 tài liệu theo doc_name.
    """
    try:
        client = qdrant_client.client
        collection_name = settings.COLLECTION_NAME

        client.delete(
            collection_name=collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="doc_name",
                        match=MatchValue(value=doc_name)
                    )
                ]
            ),
            wait=True,
        )
        log.info("  🗑 Đã xóa dữ liệu cũ của file: %s", doc_name)
        return True
    except Exception as e:
        log.error("  Không xóa được dữ liệu cũ của %s: %s", doc_name, e)
        return False


def should_ingest(file_path: Path):
    """
    Quyết định có ingest file này không.
    Return tuple:
      (action, file_hash, existing_info)

    action:
      - "new"     : file chưa có
      - "skip"    : file đã có và hash không đổi
      - "update"  : file đã có nhưng hash đổi, cần xóa cũ rồi ingest lại
    """
    file_hash = sha256_file(file_path)
    existing = get_existing_doc_info(file_path.name)

    if not existing:
        return "new", file_hash, None

    old_hash = existing.get("file_hash")

    if old_hash == file_hash:
        return "skip", file_hash, existing

    return "update", file_hash, existing


def ingest_file(file_path: Path, doc_id: str | None = None, force: bool = False, auto = True) -> int:
    log.info("\n%s", "=" * 60)
    log.info("📄 Đang xử lý: %s", file_path.name)
    log.info("%s", "=" * 60)

    action, file_hash, existing = should_ingest(file_path)

    if not force:
        if action == "skip":
            log.info("  ⏭ Bỏ qua: file không đổi, đã ingest rồi")
            log.info("     doc_name=%s", file_path.name)
            log.info("     file_hash=%s", file_hash[:16] + "...")
            return 0

        if action == "update":
            log.info("  ♻ File đã tồn tại nhưng nội dung thay đổi")
            log.info("     doc_name=%s", file_path.name)
            log.info("     old_hash=%s", str(existing.get('file_hash', ''))[:16] + "...")
            log.info("     new_hash=%s", file_hash[:16] + "...")
            delete_doc_by_name(file_path.name)

    if not doc_id:
        doc_id = str(uuid.uuid4())

    log.info("  [1/3] Parse text...")
    try:
        text_chunks = preprocess_doc(
            model=settings.GEMINI_MODEL,
            src=str(file_path),
            overwrite=True,
            to_console=False,
            auto=auto,
        )
    except Exception as e:
        log.exception("  Lỗi parse: %s", e)
        text_chunks = []

    log.info("  → %s text chunks", len(text_chunks))

    log.info("  [2/3] Extract bảng riêng...")
    tmp_dir = ROOT / "data" / "tmp_tables"
    table_items = extract_all_tables(file_path, tmp_dir)
    log.info("  → %s bảng tìm thấy", len(table_items))

    log.info("  [3/3] Embed text + table text...")
    enriched = []

    for chunk in text_chunks:
        embed_text = chunk.get("text", "") or ""

        enriched.append({
            "text": chunk.get("text", ""),
            "embed_text": embed_text,
            "pages": chunk.get("pages", []),
            "is_table": False,
        })

    for tbl in table_items:
        table_text = (tbl.get("table_text") or "").strip()
        if not table_text:
            continue

        page_value = tbl.get("page")
        page_info = [page_value] if page_value else []

        embed_text = f"[Bảng dữ liệu]\n{table_text}"

        enriched.append({
            "text": f"[Bảng]\n\n{table_text}",
            "embed_text": embed_text,
            "pages": page_info,
            "is_table": True,
        })

        log.info("  🗃 Bảng chunk text-only")

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
                    "file_hash": file_hash,
                    "pages": chunk["pages"],
                    "is_table": chunk["is_table"],
                    "created_at": datetime.now(timezone.utc).isoformat(),
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
    log.info("     file_hash=%s", file_hash[:16] + "...")
    return total


def ingest_directory(directory: Path, force: bool = False) -> None:
    files = [f for f in directory.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED]
    if not files:
        log.warning("Không có file nào trong %s", directory)
        return

    log.info("Tìm thấy %s file", len(files))

    total = 0
    for f in files:
        total += ingest_file(f, force=force)

    log.info("\n%s", "=" * 60)
    log.info("✅ HOÀN TẤT: %s files, %s chunks vào Qdrant", len(files), total)
    log.info("%s", "=" * 60)
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
    parser.add_argument("--clear", action="store_true", help="Xóa Qdrant rồi ingest lại toàn bộ")
    parser.add_argument("--force", action="store_true", help="Bỏ qua check hash, ingest lại file")
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
        ingest_file(path, force=args.force)
    else:
        ingest_directory(Path(args.dir), force=args.force)