from app.api.routes.appointments import router as appointments_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.api.routes.schedules import router as schedules_router

__all__ = [
    "appointments_router",
    "auth_router",
    "chat_router",
    "health_router",
    "schedules_router",
]
