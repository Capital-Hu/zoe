from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    id_card: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DoctorSchedule(Base):
    __tablename__ = "doctor_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doctor_name: Mapped[str] = mapped_column(String(128), nullable=False)
    department: Mapped[str] = mapped_column(String(128), nullable=False)
    schedule_date: Mapped[str] = mapped_column(String(16), nullable=False)
    time_of_day: Mapped[str] = mapped_column(String(8), nullable=False)
    total_slots: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    available_slots: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    patient_name: Mapped[str] = mapped_column(String(128), nullable=False)
    id_card: Mapped[str] = mapped_column(String(32), nullable=False)
    department: Mapped[str] = mapped_column(String(128), nullable=False)
    doctor_name: Mapped[str] = mapped_column(String(128), nullable=False, default="未指定")
    appointment_date: Mapped[str] = mapped_column(String(16), nullable=False)
    time_of_day: Mapped[str] = mapped_column(String(8), nullable=False)
    appointment_time: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="BOOKED")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


settings.data_dir.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{settings.data_dir / 'zoe.db'}", future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
