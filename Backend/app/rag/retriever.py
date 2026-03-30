import asyncio
import logging
from typing import Any

from qdrant_client.http.models import Filter, FieldCondition, MatchValue, models

from app.core.config import settings
from app.rag import embedder

logger = logging.getLogger(__name__)


def _to_list(x: Any):
    if x is None:
        return None
    if hasattr(x, "tolist"):
        return x.tolist()
    return x


class Retriever:
    def __init__(self, client, async_client=None):
        self.client = client
        self.async_client = async_client

    async def retrieve_v3(self, query: str, bot_id: int = 0):
        logger.info("Embedding query for retrieval...")

        try:
            # FIX: Chạy tác vụ sinh embedding đồng bộ trên một luồng (thread) riêng 
            # để không làm block event loop của FastAPI
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, embedder.get_embeddings, [query])
            dense_, sparse_, _ = result
        except Exception as e:
            logger.exception("Embedding failed: %s", e)
            return []

        if dense_ is None or len(dense_) == 0:
            logger.warning("Dense embedding empty")
            return []

        dense_query = _to_list(dense_[0])
        if not dense_query or len(dense_query) == 0:
            logger.warning("Dense embedding invalid")
            return []

        sparse_query = sparse_[0] if (sparse_ is not None and len(sparse_) > 0) else None

        filter_obj = None
        if bot_id > 0:
            filter_obj = Filter(
                must=[FieldCondition(key="bot_id", match=MatchValue(value=bot_id))]
            )

        top_k = getattr(settings, "TOP_K", 5)
        score_threshold = getattr(settings, "SCORE_THRESHOLD", None)
        collection_name = getattr(settings, "QDRANT_COLLECTION", None) or getattr(settings, "COLLECTION_NAME")

        try:
            if self.async_client:
                logger.info("Async hybrid retrieval (dense+sparse)")

                prefetch = [
                    models.Prefetch(
                        query=dense_query,
                        using="dense",
                        limit=100,
                        filter=filter_obj,
                        score_threshold=score_threshold,
                    )
                ]

                if sparse_query:
                    prefetch.append(
                        models.Prefetch(
                            query=models.SparseVector(
                                indices=[int(k) for k in sparse_query.keys()],
                                values=[float(v) for v in sparse_query.values()],
                            ),
                            using="sparse",
                            limit=100,
                            filter=filter_obj,
                        )
                    )

                result = await self.async_client.query_points(
                    collection_name=collection_name,
                    prefetch=prefetch,
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    with_payload=True,
                    limit=top_k,
                    query_filter=filter_obj,
                )
                return getattr(result, "points", [])

            logger.info("Sync dense retrieval (fallback)")
            sync_client = getattr(self.client, "client", self.client)

            def _sync_query():
                return sync_client.query_points(
                    collection_name=collection_name,
                    query=dense_query,
                    using="dense",
                    with_payload=True,
                    limit=top_k,
                    query_filter=filter_obj,
                    score_threshold=score_threshold,
                )

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _sync_query)
            return getattr(result, "points", [])

        except Exception as e:
            logger.exception("Qdrant search failed: %s", e)
            return []