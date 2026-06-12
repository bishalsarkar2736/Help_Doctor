from .admin import router as admin_router
from .doctors import router as doctors_router
from .auth import router as auth_router
from .doctor_availability import router as doctor_availability_router
from .appointments import router as appointments_router
from .admin_doctors import router as admin_doctors_router
from .notifications import router as notification_router
from .patients import router as patients_router
from .users import router as users_router
from .metric import router as metric_router
from .prescription import router as prescription_router
from .payments import router as payment_router
from .slots import router as slot_router
from .admin_analytics import router as admin_analytics_router
from .push import router as push_router
from .notification_preferences import router as notification_preferences_router
from .medicine_api import router as medicine_api_router
from .admin_medicine import router as admin_medicine_router
from .admin_medicine_analytics import router as admin_medicine_analytics_router
from .admin_medicine_alias_api import router as admin_medicine_alias_api_router
from .admin_medicine_ai import router as admin_medicine_ai_router
from .admin_medicine_ai_logs import router as admin_medicine_ai_logs_router
from .admin_medicine_ai_analytics import router as admin_medicine_ai_analytics_router
from .admin_medicine_ai_feedback import router as admin_medicine_ai_feedback_router
from .admin_clinic import router as admin_clinic_router
from .admin_clinic_analytics import router as admin_clinic_analytics_router
from .admin_revenue_analytics import router as admin_revenue_analytics_router
from .admin_dashboard import router as admin_dashboard_router
from .admin_clinic_logo import router as admin_clinic_logo_router
__all__ = [
    "admin_router",
    "doctors_router",
    "auth_router",
    "doctor_availability_router",
    "appointments_router",
    "admin_doctors_router",
    "notification_router",
    "patients_router",
    "users_router",
    "metric_router",
    "prescription_router",
    "payment_router",
    "slot_router",
    "admin_analytics_router",
    "push_router",
    "notification_preferences_router",
    "medicine_api_router",
    "admin_medicine_router",
    "admin_medicine_analytics_router",
    "admin_medicine_alias_api_router",
    "admin_medicine_ai_router",
    "admin_medicine_ai_logs_router",
    "admin_medicine_ai_analytics_router",
    "admin_medicine_ai_feedback_router",
    "admin_clinic_router",
    "admin_clinic_analytics_router",
    "admin_revenue_analytics_router",
    "admin_dashboard_router",
    "admin_clinic_logo_router",
]
