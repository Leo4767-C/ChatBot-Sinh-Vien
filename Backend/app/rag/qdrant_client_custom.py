from qdrant_client import QdrantClient
from qdrant_client.http import models
from app.core.config import settings
import logging

log = logging.getLogger(__name__)


class QdrantClientCustom:
    def __init__(self):
        self.collection_name = settings.QDRANT_COLLECTION
        self.client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            prefer_grpc=False,
        )

    def recreate_collection(self, vector_size: int):
        """
        Xóa collection cũ và tạo lại đúng schema hybrid:
        - dense: named dense vector
        - sparse: named sparse vector
        """
        try:
            self.client.delete_collection(collection_name=self.collection_name)
            log.info("Đã xóa collection cũ: %s", self.collection_name)
        except Exception:
            pass

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                "dense": models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams()
            },
        )
        log.info("Đã tạo lại collection hybrid: %s", self.collection_name)

    def create_collection(self, vector_size: int):
        """
        Tạo collection nếu chưa có.
        Nếu collection đã tồn tại thì giữ nguyên.
        """
        collections = self.client.get_collections().collections
        names = [c.name for c in collections]

        if self.collection_name in names:
            log.info("Collection đã tồn tại: %s", self.collection_name)
            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                "dense": models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams()
            },
        )
        log.info("Đã tạo collection mới: %s", self.collection_name)

    def delete_collection(self):
        self.client.delete_collection(collection_name=self.collection_name)
        log.info("Đã xóa collection: %s", self.collection_name)

    def upsert_vectors(self, vectors: list[dict]) -> int:
        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=v["id"],
                        vector=v["vector"],
                        payload=v["payload"],
                    )
                    for v in vectors
                ],
                wait=True,
            )
            return len(vectors)
        except Exception:
            log.exception("✗ Upsert thất bại")
            return 0


qdrant_client = QdrantClientCustom()