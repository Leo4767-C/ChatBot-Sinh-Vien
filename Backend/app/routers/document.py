import logging
import mimetypes
import uuid
from pathlib import Path

import google.generativeai as genai
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient, QdrantClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.database import ChatMessage, get_db, Document
from app.rag.retriever import Retriever
from app.storage.helper import StorageHelper
from ingest import ingest_file

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/document", tags=["document"])

_kw = {"url": settings.QDRANT_URL, "api_key": settings.QDRANT_API_KEY}
_sync = QdrantClient(**_kw, prefer_grpc=False)
_async = AsyncQdrantClient(**_kw, prefer_grpc=False)
_retriever = Retriever(client=_sync, async_client=_async)

genai.configure(api_key=settings.EFFECTIVE_GEMINI_API_KEY)

BASE_DIR = Path(__file__).resolve().parents[1]
UPLOAD_DIR = BASE_DIR / "data" / "images" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DOC_DIR = BASE_DIR / "data"

storage_helper = StorageHelper()


@router.post("/upload", tags=["document"])
async def upload_document(
        db: AsyncSession = Depends(get_db),
        *,
        file: UploadFile = File(...),
        filename: str = Form(None)
):
    logger.info("Start uploading document")
    if not filename:
        filename = Path(file.filename).stem.strip()

    filename += Path(file.filename).suffix

    full_path = storage_helper.upload_v2(filename, file)
    if not full_path:
        raise HTTPException(500, "Đã có lỗi xảy ra, vui lòng thử lại sau")

    logger.info("Start ingest document")

    doc = Document(
        id=str(uuid.uuid4()),
        filename=full_path.stem.strip(),
        original_name=full_path.name, # tên file có đuôi
        file_type="",
        file_size=0,
        # status="ok"
    )

    doc.chunk_count = ingest_file(full_path, doc.id)
    doc.status = "ok"

    logger.info("Ingest document finished")

    db.add(doc)
    await db.commit()

    return {
        "id": doc.id,
        "filename": doc.filename,
    }


@router.get("/reference/{filename}")
async def get_reference(db: AsyncSession = Depends(get_db), *, filename: str):
    if not filename:
        raise HTTPException(400, "Tên nguồn tham khảo không được để trống")

    res = await db.execute(
        select(Document)
        .where(Document.filename == filename)
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    document = res.scalars().first()
    if not document or not document.original_name:
        raise HTTPException(404, "Nguồn tham khảo hiện không thể xem")

    try:
        content = storage_helper.download_v2(document.original_name)
        if content is None:
            raise HTTPException(404, "Nguồn tham khảo hiện không thể xem")

        content_type, _ = mimetypes.guess_type(document.original_name)
        if not content_type:
            content_type = "application/octet-stream"

        return StreamingResponse(
            content,
            media_type=content_type,
        )

    except Exception as e:
        raise HTTPException(500, "Đã có lỗi xảy ra, vui lòng thử lại sau")
    finally:
        await db.close()
