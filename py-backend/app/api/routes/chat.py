from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import ensure_account, get_services
from app.db import get_db_session
from app.schemas.chat import ChatForm, CompressMemoryForm

router = APIRouter(prefix="/zoe", tags=["chat"])


@router.post("/chat")
def chat(payload: ChatForm, request: Request, session: Session = Depends(get_db_session)):
    services = get_services(request)
    if services.zoe_graph is None:
        raise HTTPException(status_code=503, detail="chat agent not initialized; please check model config")
    ensure_account(session, payload.userId)
    scoped_memory_id = f"user_{payload.userId}_mem_{payload.memoryId}"
    return StreamingResponse(
        services.zoe_graph.run_stream(memory_id=scoped_memory_id, question=payload.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/memory/compress")
def compress_memory(payload: CompressMemoryForm, request: Request, session: Session = Depends(get_db_session)):
    services = get_services(request)
    if services.zoe_graph is None:
        raise HTTPException(status_code=503, detail="chat memory service not initialized; please check model config")
    ensure_account(session, payload.userId)
    scoped_memory_id = f"user_{payload.userId}_mem_{payload.memoryId}"
    data = services.zoe_graph.memory_store.compress(scoped_memory_id)
    session_facts_count = len(data.get("session_facts", data.get("long_term_facts", [])))
    return {
        "memoryId": scoped_memory_id,
        "short_term_summary": data.get("short_term_summary", ""),
        "session_facts_count": session_facts_count,
        "long_term_facts_count": session_facts_count,
        "last_compressed_at": data.get("last_compressed_at"),
    }


@router.get("/sessions")
def list_sessions(userId: int, request: Request, session: Session = Depends(get_db_session)):
    services = get_services(request)
    ensure_account(session, userId)
    return {"sessions": services.conversation_logger.list_sessions(user_id=userId)}


@router.get("/sessions/{memory_id}")
def get_session_detail(memory_id: str, userId: int, request: Request, session: Session = Depends(get_db_session)):
    services = get_services(request)
    ensure_account(session, userId)
    data = services.conversation_logger.get_session_detail(user_id=userId, memory_id=memory_id)
    if not data:
        raise HTTPException(status_code=404, detail="session not found")
    return data
