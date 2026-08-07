"""Every model, imported so that every table reaches Base.metadata.

THIS FILE IS LOAD-BEARING FOR MIGRATIONS.

alembic/env.py does `from app.models import *` and hands Base.metadata to
autogenerate. A model that is not imported here therefore has no table in that
metadata, and autogenerate does not read it as "unknown" — it reads it as a
table nobody wants, and writes op.drop_table().

Seven models were missing. A generated migration consequently proposed dropping
audit_logs, activity_logs, prescription_templates,
prescription_template_items, medicine_assistant_queries, medicine_ai_logs,
medicine_ai_feedback and medicine_ai_error_logs — the compliance trail among
them. Nothing warns about this: the migration looks like ordinary generated
output, and the tables are gone the moment it is applied.

So: add a model here in the same commit that creates it.
tests/test_schema_drift.py fails if this drifts again.
"""

from .user import User
from .patient import Patient
from .refresh_token import RefreshToken
from .doctor import Doctor
from .doctor_availability import DoctorAvailability
from .doctor_document import DoctorDocument, DoctorDocumentType
from .doctor_rating import DoctorRating
from .generic import Generic
from .generic_alias import GenericAlias
from .user_consent import UserConsent
from .phi_access_log import PHIAccessLog, PHIAction, PHIResourceType
from .appointment import Appointment
from .notification import Notification
from .appointment_history import AppointmentStatusHistory
from .outbox_event import OutboxEvent
from .prescription import Prescription, PrescriptionItem
from .payment import Payment
from .payment_audit_log import PaymentAuditLog
from .idempotency_key import IdempotencyKey
from .doctor_slot import DoctorSlot
from .push_subscription import PushSubscription
from .outbox_dead_letter import DeadLetterEvent
from .notification_preference import NotificationPreference
from .medicine_alias import MedicineAlias
from .clinic import Clinic
from .medicine import Medicine
from .password_reset_token import PasswordResetToken
from .email_verification_token import EmailVerificationToken
from .invitation import Invitation, InvitationStatus

# Previously absent from this file — see the module docstring. Each of these
# has a table in the database that autogenerate proposed dropping.
from .activity_log import ActivityLog
from .audit_log import AuditLog
from .medicine_ai_error_log import MedicineAIErrorLog
from .medicine_ai_feedback import MedicineAIFeedback
from .medicine_ai_log import MedicineAILog
from .medicine_assistant_query import MedicineAssistantQuery
from .prescription_template import PrescriptionTemplate, PrescriptionTemplateItem