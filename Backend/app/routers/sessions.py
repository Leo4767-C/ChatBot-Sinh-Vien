import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models.database import get_db, Session, ChatMessage

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

@router.post("/")
async def create_session(db: AsyncSession = Depends(get_db)):
    s = Session(id=str(uuid.uuid4()))
    db.add(s); await db.commit(); await db.refresh(s)
    return {"id": s.id, "title": s.title,
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat()}

@router.get("/")
async def list_sessions(db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Session).order_by(Session.updated_at.desc()))
    return [{"id": s.id, "title": s.title,
             "created_at": s.created_at.isoformat(),
             "updated_at": s.updated_at.isoformat()}
            for s in r.scalars().all()]

@router.get("/{sid}/history")
async def get_history(sid: str, db: AsyncSession = Depends(get_db)):
    r = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == sid)
        .order_by(ChatMessage.created_at.asc()))
    return [{"role": m.role, "content": m.content} for m in r.scalars().all()]

@router.delete("/{sid}")
async def del_session(sid: str, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Session).where(Session.id == sid))
    if not r.scalar_one_or_none():
        raise HTTPException(404, "Không tìm thấy session")
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == sid))
    await db.execute(delete(Session).where(Session.id == sid))
    await db.commit()
    return {"ok": True}