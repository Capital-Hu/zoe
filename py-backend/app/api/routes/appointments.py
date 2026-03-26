from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import Appointment, get_db_session
from app.schemas.appointments import AppointmentCreate, AppointmentUpdate

router = APIRouter(tags=["appointments"])


@router.get("/appointments")
def list_appointments(session: Session = Depends(get_db_session)):
    rows = session.query(Appointment).order_by(Appointment.id.desc()).all()
    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "patient_name": row.patient_name,
            "id_card": row.id_card,
            "department": row.department,
            "doctor_name": row.doctor_name,
            "appointment_date": row.appointment_date,
            "time_of_day": row.time_of_day,
            "appointment_time": row.appointment_time,
            "status": row.status,
            "note": row.note,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/appointments")
def create_appointment(payload: AppointmentCreate, session: Session = Depends(get_db_session)):
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


@router.put("/appointments/{appointment_id}")
def update_appointment(appointment_id: int, payload: AppointmentUpdate, session: Session = Depends(get_db_session)):
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


@router.delete("/appointments/{appointment_id}")
def delete_appointment(appointment_id: int, session: Session = Depends(get_db_session)):
    row = session.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="appointment not found")
    session.delete(row)
    session.commit()
    return {"ok": True}
