from pydantic import BaseModel


class ScheduleCreate(BaseModel):
    doctor_name: str
    department: str
    schedule_date: str
    time_of_day: str
    total_slots: int = 20
    available_slots: int = 20


class ScheduleStop(BaseModel):
    reason: str = "停诊"


class ScheduleAdjustSlots(BaseModel):
    total_slots: int
    available_slots: int
