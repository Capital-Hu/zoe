from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.auth_utils import hash_password, verify_password
from app.db import Account, Appointment, DoctorSchedule, SessionLocal, init_db
from app.graph_flow import ZoeGraph
from app.memory_store import LayeredMemoryStore
from app.models import ModelBundle
from app.retriever import HybridRetriever
from app.schemas import (
    AppointmentCreate,
    AppointmentUpdate,
    ChatForm,
    CompressMemoryForm,
    LoginForm,
    RegisterForm,
    ScheduleAdjustSlots,
    ScheduleCreate,
    ScheduleStop,
)

app = FastAPI(title="Zoe Medical Agent (Python)")
logger = logging.getLogger(__name__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

zoe_graph: ZoeGraph | None = None


@app.on_event("startup")
def on_startup():
    global zoe_graph
    init_db()
    try:
        bundle = ModelBundle()
        retriever = HybridRetriever(bundle.embedding)
        memory_store = LayeredMemoryStore(bundle.llm)
        zoe_graph = ZoeGraph(bundle.llm, retriever, memory_store)
    except Exception as exc:
        # 允许非聊天接口（如排班管理）在模型配置缺失时正常工作
        zoe_graph = None
        logger.warning("Chat agent init skipped: %s", exc)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/auth/register")
def register(payload: RegisterForm):
    username = payload.username.strip()
    if len(username) < 3 or len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="username or password too short")

    with SessionLocal() as session:
        existed = session.query(Account).filter(Account.username == username).first()
        if existed:
            raise HTTPException(status_code=409, detail="username already exists")

        row = Account(username=username, password_hash=hash_password(payload.password))
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"userId": row.id, "username": row.username}


@app.post("/auth/login")
def login(payload: LoginForm):
    username = payload.username.strip()
    with SessionLocal() as session:
        row = session.query(Account).filter(Account.username == username).first()
        if not row or not verify_password(payload.password, row.password_hash):
            raise HTTPException(status_code=401, detail="invalid username or password")
        return {"userId": row.id, "username": row.username}


@app.post("/zoe/chat")
def chat(payload: ChatForm):
    if zoe_graph is None:
        raise HTTPException(status_code=503, detail="chat agent not initialized; please check model config")
    with SessionLocal() as session:
        account = session.query(Account).filter(Account.id == payload.userId).first()
        if not account:
            raise HTTPException(status_code=401, detail="invalid userId")
    scoped_memory_id = f"user_{payload.userId}_mem_{payload.memoryId}"
    answer = zoe_graph.run(memory_id=scoped_memory_id, question=payload.message)

    def text_stream():
        # 兼容前端流式追加逻辑，按小块返回
        for i in range(0, len(answer), 8):
            yield answer[i : i + 8]

    return StreamingResponse(text_stream(), media_type="text/stream;charset=utf-8")


@app.post("/zoe/memory/compress")
def compress_memory(payload: CompressMemoryForm):
    if zoe_graph is None:
        raise HTTPException(status_code=503, detail="chat memory service not initialized; please check model config")
    with SessionLocal() as session:
        account = session.query(Account).filter(Account.id == payload.userId).first()
        if not account:
            raise HTTPException(status_code=401, detail="invalid userId")
    scoped_memory_id = f"user_{payload.userId}_mem_{payload.memoryId}"
    data = zoe_graph.memory_store.compress(scoped_memory_id)
    return {
        "memoryId": scoped_memory_id,
        "short_term_summary": data.get("short_term_summary", ""),
        "long_term_facts_count": len(data.get("long_term_facts", [])),
        "last_compressed_at": data.get("last_compressed_at"),
    }


def _safe_memory_id(memory_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(memory_id))


def _extract_memory_suffix(scoped_memory_id: str, user_id: int) -> str:
    prefix = f"user_{user_id}_mem_"
    if scoped_memory_id.startswith(prefix):
        return scoped_memory_id[len(prefix) :]
    return scoped_memory_id


def _read_jsonl_records(file_path: Path) -> list[dict]:
    records: list[dict] = []
    if not file_path.exists():
        return records
    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


@app.get("/zoe/sessions")
def list_sessions(userId: int):
    with SessionLocal() as session:
        account = session.query(Account).filter(Account.id == userId).first()
        if not account:
            raise HTTPException(status_code=401, detail="invalid userId")

    logs_dir = Path(__file__).resolve().parents[1] / "data" / "logs"
    pattern = f"conversation_user_{userId}_mem_*.jsonl"
    items = []
    for log_file in logs_dir.glob(pattern):
        records = _read_jsonl_records(log_file)
        if not records:
            continue
        first_record = records[0]
        last_record = records[-1]
        scoped_memory_id = str(last_record.get("memory_id") or "")
        items.append(
            {
                "memoryId": _extract_memory_suffix(scoped_memory_id, userId),
                "scopedMemoryId": scoped_memory_id,
                "title": str(first_record.get("question") or "新会话")[:40],
                "turns": len(records),
                "updatedAt": last_record.get("timestamp"),
            }
        )

    items.sort(key=lambda x: x.get("updatedAt") or "", reverse=True)
    return {"sessions": items}


@app.get("/zoe/sessions/{memory_id}")
def get_session_detail(memory_id: str, userId: int):
    with SessionLocal() as session:
        account = session.query(Account).filter(Account.id == userId).first()
        if not account:
            raise HTTPException(status_code=401, detail="invalid userId")

    scoped_memory_id = f"user_{userId}_mem_{memory_id}"
    safe_scoped_memory_id = _safe_memory_id(scoped_memory_id)
    log_file = Path(__file__).resolve().parents[1] / "data" / "logs" / f"conversation_{safe_scoped_memory_id}.jsonl"
    records = _read_jsonl_records(log_file)
    if not records:
        raise HTTPException(status_code=404, detail="session not found")

    messages = []
    for record in records:
        question = record.get("question")
        answer = record.get("answer")
        if question:
            messages.append({"isUser": True, "content": str(question)})
        if answer:
            messages.append({"isUser": False, "content": str(answer)})

    return {
        "memoryId": memory_id,
        "scopedMemoryId": scoped_memory_id,
        "messages": messages,
        "turns": len(records),
        "updatedAt": records[-1].get("timestamp"),
    }


@app.get("/appointments")
def list_appointments():
    with SessionLocal() as session:
        rows = session.query(Appointment).order_by(Appointment.id.desc()).all()
        return [
            {
                "id": r.id,
                "user_id": r.user_id,
                "patient_name": r.patient_name,
                "id_card": r.id_card,
                "department": r.department,
                "doctor_name": r.doctor_name,
                "appointment_date": r.appointment_date,
                "time_of_day": r.time_of_day,
                "appointment_time": r.appointment_time,
                "status": r.status,
                "note": r.note,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]


@app.post("/appointments")
def create_appointment(payload: AppointmentCreate):
    with SessionLocal() as session:
        row = Appointment(
            user_id=payload.user_id,
            patient_name=payload.patient_name,
            id_card=payload.id_card,
            department=payload.department,
            doctor_name=payload.doctor_name,
            appointment_date=payload.appointment_date,
            time_of_day=payload.time_of_day,
            appointment_time=payload.appointment_time,
            status=payload.status,
            note=payload.note,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"id": row.id}


@app.put("/appointments/{appointment_id}")
def update_appointment(appointment_id: int, payload: AppointmentUpdate):
    with SessionLocal() as session:
        row = session.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="appointment not found")
        for field in (
            "patient_name",
            "id_card",
            "department",
            "doctor_name",
            "appointment_date",
            "time_of_day",
            "appointment_time",
            "status",
            "note",
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(row, field, value)
        session.commit()
        return {"ok": True}


@app.delete("/appointments/{appointment_id}")
def delete_appointment(appointment_id: int):
    with SessionLocal() as session:
        row = session.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="appointment not found")
        session.delete(row)
        session.commit()
        return {"ok": True}


@app.get("/schedules")
def list_schedules(department: str | None = None, schedule_date: str | None = None):
    with SessionLocal() as session:
        query = session.query(DoctorSchedule)
        if department:
            query = query.filter(DoctorSchedule.department == department)
        if schedule_date:
            query = query.filter(DoctorSchedule.schedule_date == schedule_date)
        rows = query.order_by(DoctorSchedule.schedule_date.desc(), DoctorSchedule.id.desc()).all()
        return [
            {
                "id": r.id,
                "doctor_name": r.doctor_name,
                "department": r.department,
                "schedule_date": r.schedule_date,
                "time_of_day": r.time_of_day,
                "total_slots": r.total_slots,
                "available_slots": r.available_slots,
                "status": r.status,
                "stop_reason": r.stop_reason,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]


@app.post("/schedules")
def create_schedule(payload: ScheduleCreate):
    if payload.available_slots > payload.total_slots:
        raise HTTPException(status_code=400, detail="available_slots cannot exceed total_slots")
    with SessionLocal() as session:
        existed = (
            session.query(DoctorSchedule)
            .filter(DoctorSchedule.doctor_name == payload.doctor_name)
            .filter(DoctorSchedule.schedule_date == payload.schedule_date)
            .filter(DoctorSchedule.time_of_day == payload.time_of_day)
            .first()
        )
        if existed:
            raise HTTPException(status_code=409, detail="schedule already exists")
        row = DoctorSchedule(
            doctor_name=payload.doctor_name,
            department=payload.department,
            schedule_date=payload.schedule_date,
            time_of_day=payload.time_of_day,
            total_slots=payload.total_slots,
            available_slots=payload.available_slots,
            status="ACTIVE",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"id": row.id}


@app.put("/schedules/{schedule_id}/stop")
def stop_schedule(schedule_id: int, payload: ScheduleStop):
    with SessionLocal() as session:
        row = session.query(DoctorSchedule).filter(DoctorSchedule.id == schedule_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="schedule not found")
        row.status = "STOPPED"
        row.stop_reason = payload.reason
        row.available_slots = 0
        session.commit()
        return {"ok": True}


@app.put("/schedules/{schedule_id}/slots")
def adjust_schedule_slots(schedule_id: int, payload: ScheduleAdjustSlots):
    if payload.total_slots < 0 or payload.available_slots < 0:
        raise HTTPException(status_code=400, detail="slots must be non-negative")
    if payload.available_slots > payload.total_slots:
        raise HTTPException(status_code=400, detail="available_slots cannot exceed total_slots")
    with SessionLocal() as session:
        row = session.query(DoctorSchedule).filter(DoctorSchedule.id == schedule_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="schedule not found")
        row.total_slots = payload.total_slots
        row.available_slots = payload.available_slots
        if row.status == "STOPPED" and payload.available_slots > 0:
            row.status = "ACTIVE"
            row.stop_reason = None
        session.commit()
        return {"ok": True}
