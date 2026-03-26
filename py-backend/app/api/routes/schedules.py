from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import DoctorSchedule, get_db_session
from app.schemas.schedules import ScheduleAdjustSlots, ScheduleCreate, ScheduleStop

router = APIRouter(tags=["schedules"])


@router.get("/schedules")
def list_schedules(
    department: str | None = None,
    schedule_date: str | None = None,
    session: Session = Depends(get_db_session),
):
    query = session.query(DoctorSchedule)
    if department:
        query = query.filter(DoctorSchedule.department == department)
    if schedule_date:
        query = query.filter(DoctorSchedule.schedule_date == schedule_date)
    rows = query.order_by(DoctorSchedule.schedule_date.desc(), DoctorSchedule.id.desc()).all()
    return [
        {
            "id": row.id,
            "doctor_name": row.doctor_name,
            "department": row.department,
            "schedule_date": row.schedule_date,
            "time_of_day": row.time_of_day,
            "total_slots": row.total_slots,
            "available_slots": row.available_slots,
            "status": row.status,
            "stop_reason": row.stop_reason,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/schedules")
def create_schedule(payload: ScheduleCreate, session: Session = Depends(get_db_session)):
    if payload.available_slots > payload.total_slots:
        raise HTTPException(status_code=400, detail="available_slots cannot exceed total_slots")
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


@router.put("/schedules/{schedule_id}/stop")
def stop_schedule(schedule_id: int, payload: ScheduleStop, session: Session = Depends(get_db_session)):
    row = session.query(DoctorSchedule).filter(DoctorSchedule.id == schedule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="schedule not found")
    row.status = "STOPPED"
    row.stop_reason = payload.reason
    row.available_slots = 0
    session.commit()
    return {"ok": True}


@router.put("/schedules/{schedule_id}/slots")
def adjust_schedule_slots(
    schedule_id: int,
    payload: ScheduleAdjustSlots,
    session: Session = Depends(get_db_session),
):
    if payload.total_slots < 0 or payload.available_slots < 0:
        raise HTTPException(status_code=400, detail="slots must be non-negative")
    if payload.available_slots > payload.total_slots:
        raise HTTPException(status_code=400, detail="available_slots cannot exceed total_slots")
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
