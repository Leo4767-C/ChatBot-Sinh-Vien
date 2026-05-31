"""
test_retriever.py — Unit tests cho module retriever.

Sử dụng mock để tránh phụ thuộc Qdrant/embedding model thật.
Bao gồm:
  - _to_list: chuyển numpy array → list
  - Retriever: init, retrieve_v3 (async)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.rag.retriever import _to_list, Retriever


class TestToList:
    """Chuyển đổi output sang list Python."""

    def test_none(self):
        assert _to_list(None) is None

    def test_plain_list(self):
        assert _to_list([1, 2, 3]) == [1, 2, 3]

    def test_numpy_like(self):
        """Object có .tolist() method (numpy array mock)."""
        obj = MagicMock()
        obj.tolist.return_value = [0.1, 0.2, 0.3]
        assert _to_list(obj) == [0.1, 0.2, 0.3]

    def test_scalar(self):
        assert _to_list(42) == 42


class TestRetrieverInit:
    def test_init(self):
        client = MagicMock()
        async_client = AsyncMock()
        r = Retriever(client=client, async_client=async_client)
        assert r.client is client
        assert r.async_client is async_client

    def test_init_without_async(self):
        r = Retriever(client=MagicMock())
        assert r.async_client is None


@pytest.mark.asyncio
class TestRetrieverRetrieveV3:
    """Test retrieve_v3 với mock embedding + Qdrant."""

    async def test_returns_empty_on_embedding_failure(self):
        r = Retriever(client=MagicMock(), async_client=AsyncMock())
        with patch("app.rag.retriever.embedder") as mock_emb:
            mock_emb.get_embeddings.side_effect = RuntimeError("Model error")
            result = await r.retrieve_v3("test query")
            assert result == []

    async def test_returns_empty_on_empty_dense(self):
        r = Retriever(client=MagicMock(), async_client=AsyncMock())
        with patch("app.rag.retriever.embedder") as mock_emb:
            mock_emb.get_embeddings.return_value = ([], [])
            result = await r.retrieve_v3("test query")
            assert result == []

    async def test_returns_empty_on_none_dense(self):
        r = Retriever(client=MagicMock(), async_client=AsyncMock())
        with patch("app.rag.retriever.embedder") as mock_emb:
            mock_emb.get_embeddings.return_value = (None, None)
            result = await r.retrieve_v3("test query")
            assert result == []

    async def test_async_client_query(self):
        """Test thành công với async client."""
        mock_async = AsyncMock()
        mock_point = MagicMock()
        mock_point.payload = {"content": "test content"}
        mock_result = MagicMock()
        mock_result.points = [mock_point]
        mock_async.query_points.return_value = mock_result

        r = Retriever(client=MagicMock(), async_client=mock_async)

        with patch("app.rag.retriever.embedder") as mock_emb:
            dense = [[0.1] * 1024]
            sparse = [{"1": 0.5, "2": 0.3}]
            mock_emb.get_embeddings.return_value = (dense, sparse)

            result = await r.retrieve_v3("test query")
            assert len(result) == 1
            assert result[0].payload["content"] == "test content"

    async def test_sync_fallback(self):
        """Khi không có async_client → dùng sync client."""
        mock_sync = MagicMock()
        mock_result = MagicMock()
        mock_result.points = []
        # Retriever accesses .client attribute then calls .query_points()
        mock_sync.client = mock_sync
        mock_sync.query_points.return_value = mock_result

        r = Retriever(client=mock_sync, async_client=None)

        with patch("app.rag.retriever.embedder") as mock_emb:
            dense = [[0.1] * 1024]
            sparse = [{}]
            mock_emb.get_embeddings.return_value = (dense, sparse)

            result = await r.retrieve_v3("test query")
            assert result == []

    async def test_qdrant_error_returns_empty(self):
        mock_async = AsyncMock()
        mock_async.query_points.side_effect = Exception("Qdrant down")

        r = Retriever(client=MagicMock(), async_client=mock_async)

        with patch("app.rag.retriever.embedder") as mock_emb:
            dense = [[0.1] * 1024]
            sparse = [{}]
            mock_emb.get_embeddings.return_value = (dense, sparse)

            result = await r.retrieve_v3("test query")
            assert result == []

    async def test_bot_id_filter(self):
        """Khi bot_id > 0 → tạo filter object."""
        mock_async = AsyncMock()
        mock_result = MagicMock()
        mock_result.points = []
        mock_async.query_points.return_value = mock_result

        r = Retriever(client=MagicMock(), async_client=mock_async)

        with patch("app.rag.retriever.embedder") as mock_emb:
            dense = [[0.1] * 1024]
            sparse = [{}]
            mock_emb.get_embeddings.return_value = (dense, sparse)

            await r.retrieve_v3("test", bot_id=5)
            call_kwargs = mock_async.query_points.call_args
            assert call_kwargs is not None
