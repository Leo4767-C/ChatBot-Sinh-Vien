import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import ChatMessage, Session, get_db

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _parse_meta(raw: str | None) -> dict:
    if not raw:
        return {}

    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"sources": [s for s in raw.split("|") if s]}


@router.post("/")
async def create_session(db: AsyncSession = Depends(get_db)):
    s = Session(id=str(uuid.uuid4()))
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return {
        "id": s.id,
        "title": s.title,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


@router.get("/")
async def list_sessions(db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Session).order_by(Session.updated_at.desc()))
    return [
        {
            "id": s.id,
            "title": s.title,
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat(),
        }
        for s in r.scalars().all()
    ]


@router.get("/{sid}/history")
async def get_history(sid: str, db: AsyncSession = Depends(get_db)):
    r = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == sid)
        .order_by(ChatMessage.created_at.asc())
    )

    items = []
    for m in r.scalars().all():
      meta = _parse_meta(m.source_docs)
      items.append({
          "role": m.role,
          "content": m.content,
          "sources": meta.get("sources", []),
          "images": meta.get("images", []),
      })

    return items


@router.delete("/{sid}")
async def del_session(sid: str, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Session).where(Session.id == sid))
    if not r.scalar_one_or_none():
        raise HTTPException(404, "Không tìm thấy session")

    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == sid))
    await db.execute(delete(Session).where(Session.id == sid))
    await db.commit()
    return {"ok": True}