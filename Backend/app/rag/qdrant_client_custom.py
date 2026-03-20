import logging

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.core.config import settings

logger = logging.getLogger(__name__)

QDRANT_URL = settings.QDRANT_URL
QDRANT_API_KEY = settings.QDRANT_API_KEY
COLLECTION_NAME = settings.COLLECTION_NAME


class QdrantClientCustom:
    def __init__(self, url: str, api_key: str | None = None):
        self.client = QdrantClient(url=url, api_key=api_key)

    def collection_exists(self) -> bool:
        try:
            return self.client.collection_exists(collection_name=COLLECTION_NAME)
        except Exception as e:
            logger.error("Error checking collection existence: %s", e)
            return False

    def create_collection(self, vector_size: int):
        try:
            if self.collection_exists():
                logger.info("[Qdrant] Collection already exists: %s", COLLECTION_NAME)
                return

            self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info("[Qdrant] Created collection: %s", COLLECTION_NAME)
        except Exception as e:
            logger.error("Error creating collection: %s", e)

    def upsert_vectors(self, points) -> int:
        """
        Upsert từng point để tránh lỗi payload quá lớn.
        Trả về số point upsert thành công.
        """
        if not points:
            return 0

        success = 0

        for i, point in enumerate(points, start=1):
            try:
                self.client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=[point],
                    wait=True,
                )
                logger.info("  → Upserted batch %s: 1 vectors", i)
                success += 1
            except Exception as e:
                logger.error("  ✗ Upsert thất bại batch %s", i)
                logger.exception(e)

        return success

    def delete_collection(self):
        try:
            if self.collection_exists():
                self.client.delete_collection(collection_name=COLLECTION_NAME)
                logger.info("[Qdrant] Deleted collection: %s", COLLECTION_NAME)
        except Exception as e:
            logger.error("Error deleting collection: %s", e)


qdrant_client = QdrantClientCustom(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
)