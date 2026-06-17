from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.payment import Payment
from app.models.appointment import Appointment, AppointmentStatus
from app.try_except.exceptions import BadRequestError, NotFoundError
from app.services.outbox_service import publish_event
from app.utils.db_retry import with_retry
from datetime import datetime
from app.core.time import UTC
# ✅ ADD THIS
from app.services.appointment_transition_service import (
    transition_appointment_locked,
)
from app.models.user import UserRole
from app.schemas.event import (
    PaymentSuccessEvent,
)

from app.services.domain_event_service import (
    publish_domain_event,
)

import logging

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.tracing import (
    inject_trace_attributes,
)

from app.services.activity_log_service import (
    log_activity,
)

from app.models.enums.activity_action import (
    ActivityAction,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


async def create_payment(
    *,
    db: AsyncSession,
    appointment_id: int,
    patient_id: int,
    amount: float,
    method: str,
) -> Payment:
    
    with tracer.start_as_current_span(
        "create_payment"
    ) as span:

        inject_trace_attributes(
            user_id=patient_id,
            appointment_id=appointment_id,
        )

        try:

            span.set_attribute(
                "payment.amount",
                float(amount),
            )

            span.set_attribute(
                "payment.method",
                method,
            )

            result = await db.execute(
                select(Appointment).where(
                    Appointment.id == appointment_id
                )
            )

            appointment = result.scalar_one_or_none()

            if not appointment:
                raise NotFoundError(
                    "Appointment not found"
                )
            
            if appointment.patient_id != patient_id:
                raise BadRequestError(
                    "Appointment does not belong to patient"
                )
            
            # Duplicate payment protection
            existing_payment_result = (
                await db.execute(
                    select(Payment).where(
                        Payment.appointment_id
                        == appointment_id
                    )
                )
            )

            existing_payment = (
                existing_payment_result
                .scalar_one_or_none()
            )

            if existing_payment:

                logger.warning(
                    "payment_already_exists",
                    extra={
                        "appointment_id": (
                            appointment_id
                        ),
                        "payment_id": (
                            existing_payment.id
                        ),
                        "patient_id": (
                            patient_id
                        ),
                    },
                )

                raise BadRequestError(
                    "Payment already exists"
                )


            payment = Payment(
                appointment_id=appointment_id,
                patient_id=patient_id,
                amount=amount,
                method=method,
                clinic_id=appointment.clinic_id,
                status="PENDING",
            )

            db.add(payment)

            await db.flush()
            await db.refresh(payment)

            span.set_attribute(
                "payment.id",
                payment.id,
            )
            logger.info(
                "payment_created",
                extra={
                    "payment_id": payment.id,
                    "appointment_id": appointment_id,
                    "patient_id": patient_id,
                    "amount": float(amount),
                    "method": method,
                },
            )

            span.set_status(
                Status(StatusCode.OK)
            )

                

            return payment
        
        except Exception as e:

            span.record_exception(e)

            span.set_status(
                Status(
                    StatusCode.ERROR,
                    str(e),
                )
            )

            logger.exception(
                "create_payment_failed",
                extra={
                    "appointment_id": appointment_id,
                    "patient_id": patient_id,
                    "method": method,
                },
            )

            raise


async def mark_payment_success(
    *,
    db: AsyncSession,
    transaction_id: str,
    gateway_payment_id: str,
    paid_amount: float,
    correlation_id: str | None = None,
):
    
    with tracer.start_as_current_span(
        "mark_payment_success"
    ) as span:
        
        inject_trace_attributes()
        
        try:

            span.set_attribute(
                "gateway_payment_id",
                gateway_payment_id,
            )

            span.set_attribute(
                "transaction_id",
                transaction_id,
            )

            span.set_attribute(
                "paid_amount",
                float(paid_amount),
            )

            if correlation_id:

                span.set_attribute(
                    "correlation_id",
                    correlation_id or "",
                )
            
            logger.info(
                "payment_success_started",
                extra={
                    "gateway_payment_id": gateway_payment_id,
                    "transaction_id": transaction_id,
                    "paid_amount": float(paid_amount),
                    "correlation_id": correlation_id,
                },
            )

            result = await db.execute(
                select(Payment).where(
                    Payment.gateway_payment_id == gateway_payment_id
                )
            )

            payment = result.scalar_one_or_none()

            if payment:

                inject_trace_attributes(
                    user_id=payment.patient_id,
                    appointment_id=payment.appointment_id,
                )

                span.set_attribute(
                    "payment_id",
                    payment.id,
                )

                span.set_attribute(
                    "patient_id",
                    payment.patient_id,
                )

            if not payment:

                logger.warning(
                    "payment_not_found",
                    extra={
                        "gateway_payment_id": gateway_payment_id,
                    },
                )

                raise NotFoundError("Payment not found")

            # idempotency
            if payment.status == "SUCCESS":

                logger.info(
                    "payment_already_processed",
                    extra={
                        "payment_id": payment.id,
                        "transaction_id": transaction_id,
                    },
                )

                span.set_status(
                    Status(StatusCode.OK)
                )

                return payment
            
            # AMOUNT VALIDATION
            if float(payment.amount) != float(paid_amount):

                logger.warning(
                    "payment_amount_mismatch",
                    extra={
                        "payment_id": payment.id,
                        "expected_amount": float(payment.amount),
                        "received_amount": float(paid_amount),
                    },
                )

                raise BadRequestError("Payment amount mismatch")


            # DB TRANSACTION
            async def _run():

                payment.status = "SUCCESS"
                payment.transaction_id = transaction_id

                await db.flush()

                appointment = await db.get(
                    Appointment,
                    payment.appointment_id,
                )

                if not appointment:

                    logger.warning(
                        "appointment_not_found_for_payment",
                        extra={
                            "payment_id": payment.id,
                            "appointment_id": (
                                payment.appointment_id
                            ),
                        },
                    )

                    raise NotFoundError("Appointment not found")

                await transition_appointment_locked(
                    db=db,
                    appointment=appointment,
                    new_status=AppointmentStatus.CONFIRMED,
                    changed_by=payment.patient_id,
                    actor_role=UserRole.PATIENT,
                    correlation_id=correlation_id,
                )

                return payment, appointment

            payment, appointment = await with_retry(
                _run,
                db,
                operation="payment_success",
            )

            inject_trace_attributes(
                user_id=payment.patient_id,
                appointment_id=appointment.id,
            )

            span.set_attribute(
                "appointment_id",
                appointment.id,
            )

            now = datetime.now(UTC).isoformat()

            event = PaymentSuccessEvent(
                event_type="PAYMENT_SUCCESS",

                schema_version=1,
                occurred_at=now,

                aggregate_type="payment",
                aggregate_id=payment.id,

                actor={
                    "id": payment.patient_id,
                    "role": UserRole.PATIENT.name,
                },

                correlation_id=correlation_id,
                causation_id=None,

                user_id=payment.patient_id,
                appointment_id=appointment.id,
            )

            await publish_domain_event(
                db=db,
                event=event,
            )

            logger.info(
                "payment_marked_success",
                extra={
                    "payment_id": payment.id,
                    "appointment_id": appointment.id,
                    "patient_id": payment.patient_id,
                    "transaction_id": transaction_id,
                    "correlation_id": correlation_id,
                },
            )

            span.set_status(
                Status(StatusCode.OK)
            )

            await log_activity(
                db=db,
                actor_id=payment.patient_id,
                action=ActivityAction.PAYMENT_SUCCESS,
                entity_type="payment",
                entity_id=payment.id,
            )

            return payment
        
        except Exception as e:

            span.record_exception(e)

            span.set_status(
                Status(
                    StatusCode.ERROR,
                    str(e),
                )
            )

            logger.exception(
                "mark_payment_success_failed",
                extra={
                    "gateway_payment_id": gateway_payment_id,
                    "transaction_id": transaction_id,
                    "correlation_id": correlation_id,
                },
            )

            raise