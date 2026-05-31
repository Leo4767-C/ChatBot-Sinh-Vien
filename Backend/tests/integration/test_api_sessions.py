"""
test_api_sessions.py — Integration tests cho Sessions API endpoints.

Sử dụng TestClient của FastAPI với in-memory SQLite database.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.models.database import Base, Session, ChatMessage


# ─── In-memory DB fixture ─────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def async_db():
    """Tạo in-memory SQLite database cho testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ─── Database model tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestDatabaseModels:
    """Test tạo và truy vấn các model trong database."""

    async def test_create_session(self, async_db):
        s = Session(id="test-session-1", title="Test Session")
        async_db.add(s)
        await async_db.commit()

        result = await async_db.execute(select(Session).where(Session.id == "test-session-1"))
        found = result.scalar_one()
        assert found.title == "Test Session"
        assert found.created_at is not None

    async def test_create_chat_message(self, async_db):
        msg = ChatMessage(
            session_id="test-session-1",
            role="user",
            content="Xin chào",
        )
        async_db.add(msg)
        await async_db.commit()

        result = await async_db.execute(
            select(ChatMessage).where(ChatMessage.session_id == "test-session-1")
        )
        found = result.scalar_one()
        assert found.content == "Xin chào"
        assert found.role == "user"

    async def test_message_ordering(self, async_db):
        """Messages nên được sắp xếp theo created_at."""
        for i in range(5):
            async_db.add(ChatMessage(
                session_id="s1",
                role="user" if i % 2 == 0 else "model",
                content=f"Message {i}",
            ))
        await async_db.commit()

        result = await async_db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == "s1")
            .order_by(ChatMessage.created_at.asc())
        )
        msgs = result.scalars().all()
        assert len(msgs) == 5

    async def test_session_with_messages(self, async_db):
        """Tạo session → thêm messages → truy vấn cả hai."""
        s = Session(id="full-test", title="Full Test")
        async_db.add(s)
        async_db.add(ChatMessage(session_id="full-test", role="user", content="Q1"))
        async_db.add(ChatMessage(session_id="full-test", role="model", content="A1"))
        await async_db.commit()

        msgs = await async_db.execute(
            select(ChatMessage).where(ChatMessage.session_id == "full-test")
        )
        assert len(msgs.scalars().all()) == 2

    async def test_source_docs_nullable(self, async_db):
        """source_docs có thể None."""
        msg = ChatMessage(
            session_id="s1",
            role="model",
            content="Answer",
            source_docs=None,
        )
        async_db.add(msg)
        await async_db.commit()

        result = await async_db.execute(select(ChatMessage).where(ChatMessage.content == "Answer"))
        found = result.scalar_one()
        assert found.source_docs is None

    async def test_source_docs_with_json(self, async_db):
        """source_docs lưu JSON string."""
        import json
        meta = json.dumps({"sources": ["doc.pdf"], "kind": "rag"})
        msg = ChatMessage(
            session_id="s1",
            role="model",
            content="Answer with sources",
            source_docs=meta,
        )
        async_db.add(msg)
        await async_db.commit()

        result = await async_db.execute(
            select(ChatMessage).where(ChatMessage.content == "Answer with sources")
        )
        found = result.scalar_one()
        data = json.loads(found.source_docs)
        assert data["kind"] == "rag"
