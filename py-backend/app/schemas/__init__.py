from app.schemas.appointments import AppointmentCreate, AppointmentUpdate
from app.schemas.auth import LoginForm, RegisterForm
from app.schemas.chat import ChatForm, CompressMemoryForm
from app.schemas.schedules import ScheduleAdjustSlots, ScheduleCreate, ScheduleStop

__all__ = [
    "AppointmentCreate",
    "AppointmentUpdate",
    "ChatForm",
    "CompressMemoryForm",
    "LoginForm",
    "RegisterForm",
    "ScheduleAdjustSlots",
    "ScheduleCreate",
    "ScheduleStop",
]
