from .doctors import router as doctors_router
from .auth import router as auth_router
from .doctor_availability import router as doctor_availability_router
from .appointments import router as appointments_router
from .appointments import router as appointments_router
from .doctors import router as doctors_router
from .doctor_availability import router as doctor_availability_router
from .appointments import router as appointments_router
from .admin_doctors import router as admin_doctors_router
from .notifications import router as notification_router





__all__ = ["doctors_router", "auth_router"]
