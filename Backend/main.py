from contextlib import asynccontextmanager
import logging, os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.core.config import settings
from app.models.database import init_db
from app.rag.qdrant_client_custom import qdrant_client
from app.routers import chat, sessions, document

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")

# SỬA Ở ĐÂY: ảnh thật đang nằm trong app/data/images
BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "app" / "data" / "images"
IMG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    try:
        qdrant_client.create_collection(vector_size=settings.EMBEDDING_VECTOR_SIZE)
        logger.info("✅ Qdrant collection checked/created")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Qdrant: {e}")

    yield


app = FastAPI(title="NCKH StudyBot API v3.1", version="3.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# Serve ảnh tại /images/*
app.mount("/images", StaticFiles(directory=str(IMG_DIR)), name="images")

app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(document.router)


@app.get("/")
async def root():
    return {"status": "ok", "version": "3.1.0"}


@app.get("/health")
async def health():
    from app.rag.qdrant_client_custom import qdrant_client
    from app.core.config import settings
    try:
        n = qdrant_client.client.get_collection(settings.COLLECTION_NAME).points_count
    except Exception:
        n = 0
    return {"status": "healthy", "qdrant_chunks": n}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)