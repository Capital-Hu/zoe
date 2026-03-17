from pydantic import BaseModel


class ChatForm(BaseModel):
    userId: int
    memoryId: str
    message: str


class CompressMemoryForm(BaseModel):
    userId: int
    memoryId: str


class RegisterForm(BaseModel):
    username: str
    password: str


class LoginForm(BaseModel):
    username: str
    password: str


class AppointmentCreate(BaseModel):
    user_id: int
    patient_name: str
    id_card: str
    department: str
    doctor_name: str = "未指定"
    appointment_date: str
    time_of_day: str
    appointment_time: str
    status: str = "BOOKED"
    note: str | None = None


class AppointmentUpdate(BaseModel):
    patient_name: str | None = None
    id_card: str | None = None
    department: str | None = None
    doctor_name: str | None = None
    appointment_date: str | None = None
    time_of_day: str | None = None
    appointment_time: str | None = None
    status: str | None = None
    note: str | None = None


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
