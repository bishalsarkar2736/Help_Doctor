from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import uuid4
from app.models.payment import Payment
from app.models.appointment import Appointment, AppointmentStatus
from app.try_except.exceptions import BadRequestError, NotFoundError
from app.utils.db_retry import with_retry
from app.core.metrics import payments_success_total
from datetime import datetime
from app.core.time import UTC
from app.services.appointment_transition_service import (
    transition_appointment_locked,
)
from app.models.user import UserRole
from app.schemas.event import (
    PaymentSuccessEvent,
    PaymentPendingEvent,
    PaymentFailedEvent,
)
from decimal import Decimal
from app.services.domain_event_service import (
    publish_domain_event,
)
from sqlalchemy.exc import IntegrityError
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
from app.models.enums.payment_status import (
    PaymentStatus,
)



logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


async def create_payment(
    *,
    db: AsyncSession,
    appointment_id: int,
    patient_id: int,
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

            result = await db.execute(
                select(Appointment).where(
                    Appointment.id == appointment_id,
                    Appointment.patient_id == patient_id,
                )
                .with_for_update()
            )

            appointment = result.scalar_one_or_none()

            if not appointment:
                raise NotFoundError(
                    "Appointment not found"
                )
            
            if appointment.status not in {
                AppointmentStatus.PENDING,
            }:
                raise BadRequestError(
                    "Payment is not allowed for this appointment"
                )
            
            span.set_attribute(
                "payment.amount",
                float(appointment.consultation_fee),
            )

            span.set_attribute(
                "payment.method",
                method,
            )
            
            
            # Duplicate payment protection
            existing_payment_result = await db.execute(
                select(Payment).where(
                    Payment.appointment_id == appointment_id,
                    Payment.clinic_id == appointment.clinic_id,
                    Payment.status.in_(
                        [
                            PaymentStatus.PENDING,
                            PaymentStatus.SUCCESS,
                        ]
                    ),
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
                        "appointment_id": appointment_id,
                        "payment_id": existing_payment.id,
                        "patient_id": patient_id,
                        "payment_status": (
                            existing_payment.status
                        ),
                    },
                )

                if (
                    existing_payment.status
                    == PaymentStatus.SUCCESS
                ):
                    raise BadRequestError(
                        "Appointment already paid"
                    )

                raise BadRequestError(
                    "Payment already exists"
                )


            payment = Payment(
                appointment_id=appointment_id,
                patient_id=patient_id,
                method=method,
                clinic_id=appointment.clinic_id,
                amount=appointment.consultation_fee,
                status=PaymentStatus.PENDING,
                public_invoice_id=f"INV-{uuid4().hex[:12].upper()}",
            )

            db.add(payment)

            await db.flush()
            await db.refresh(payment)

            span.set_attribute(
                "payment.id",
                payment.id,
            )

            # PENDING is not a transition, so there is no mark_payment_pending to
            # publish from. It is the state a Payment is BORN in, and this is the
            # only place in the application that constructs one -- so creation is
            # the authoritative point, and covering it covers every legitimate
            # path by construction.
            #
            # No duplicate is possible for a payment that is already PENDING: the
            # guard above raises BadRequestError before reaching this line, and
            # idx_unique_pending_payment (a partial unique index on
            # appointment_id WHERE status = 'PENDING') closes the race, surfacing
            # as the IntegrityError already handled below. Both fire before the
            # publish rather than after.
            #
            # After flush and refresh because the event needs payment.id, and
            # inside the caller's transaction so the payment row and its outbox
            # event are written atomically.
            await publish_domain_event(
                db=db,
                event=PaymentPendingEvent(
                    event_type="PAYMENT_PENDING",

                    schema_version=1,
                    occurred_at=datetime.now(UTC).isoformat(),

                    aggregate_type="payment",
                    aggregate_id=payment.id,

                    actor={
                        "id": payment.patient_id,
                        "role": UserRole.PATIENT.name,
                    },

                    causation_id=None,

                    user_id=payment.patient_id,
                    appointment_id=appointment_id,
                ),
            )

            logger.info(
                "payment_created",
                extra={
                    "payment_id": payment.id,
                    "appointment_id": appointment_id,
                    "patient_id": patient_id,
                    "amount": float(payment.amount),
                    "method": method,
                },
            )

            span.set_status(
                Status(StatusCode.OK)
            )

            return payment
        
        
        except IntegrityError:
            #await db.rollback()

            logger.warning(
                "duplicate_pending_payment",
                extra={
                    "appointment_id": appointment_id,
                    "patient_id": patient_id,
                },
            )

            raise BadRequestError(
                "Payment already exists"
            )
        

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
    paid_amount: Decimal,
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
                .with_for_update()
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
            #if payment.status == "SUCCESS":
            if payment.status == PaymentStatus.SUCCESS:

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
            expected_amount = Decimal(payment.amount)
            received_amount = Decimal(paid_amount)

            if expected_amount != received_amount:

                logger.warning(
                    "payment_amount_mismatch",
                    extra={
                        "payment_id": payment.id,
                        "expected_amount": float(expected_amount),
                        "received_amount": float(received_amount),
                    },
                )

                raise BadRequestError("Payment amount mismatch")


            existing_payment_id = await db.scalar(
                select(Payment.id).where(
                    Payment.transaction_id == transaction_id,
                    Payment.id != payment.id,
                )
            )

            if existing_payment_id:

                logger.error(
                    "duplicate_transaction_id_detected",
                    extra={
                        "transaction_id": transaction_id,
                        "payment_id": payment.id,
                    },
                )

                raise BadRequestError(
                    "Transaction already processed"
                )


            # DB TRANSACTION
            async def _run():

                payment.status = PaymentStatus.SUCCESS
                payment.transaction_id = transaction_id

                await db.flush()

                appointment = await db.scalar(
                    select(Appointment).where(
                        Appointment.id 
                        == payment.appointment_id,
                        Appointment.clinic_id 
                        == payment.clinic_id,
                    )
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


            try:
                payment, appointment = await with_retry(
                    _run,
                    db,
                    operation="payment_success",
                )
            except IntegrityError:
                logger.warning(
                    "duplicate_transaction_id_race",
                    extra={
                        "gateway_payment_id": gateway_payment_id,
                        "transaction_id": transaction_id,
                    },
                )
                raise BadRequestError("Transaction already processed")


            payments_success_total.inc()

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
                clinic_id=payment.clinic_id,
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



async def get_payment_by_invoice_id(
    *,
    db: AsyncSession,
    public_invoice_id: str,
):
    result = await db.execute(
        select(Payment).where(
            Payment.public_invoice_id
            == public_invoice_id
        )
    )

    return result.scalar_one_or_none()



async def mark_payment_failed(
    *,
    db: AsyncSession,
    gateway_payment_id: str,
    reason: str,
):
    
    result = await db.execute(
        select(Payment)
        .where(
            Payment.gateway_payment_id
            == gateway_payment_id
        )
        .with_for_update()
    )

    payment = result.scalar_one_or_none()

    if not payment:
        raise NotFoundError(
            "Payment not found"
        )

    if payment.status != PaymentStatus.PENDING:
        return payment

    payment.status = PaymentStatus.FAILED

    payment.payment_metadata = {
        **(payment.payment_metadata or {}),
        "failure_reason": reason,
    }

    await db.flush()

    # Published HERE rather than at either call site, because there are two:
    # the bKash webhook (_handle_failed_bkash_payment) and the scheduled
    # reconciliation job. Publishing at one would leave a payment that failed
    # the other way notifying nobody, and the patient cannot tell which route
    # marked their payment.
    #
    # It sits after the PENDING guard above, so the event fires on the
    # PENDING -> FAILED transition only. A re-delivered webhook returns early
    # and publishes nothing the second time -- the idempotency the outbox
    # already provides per event_id is reinforced by never creating the
    # duplicate in the first place.
    #
    # `reason` is deliberately NOT carried on the event. It is unbounded gateway
    # text and every consumer is a patient-facing channel; it stays in
    # payment_metadata, where it is available to staff in the application.
    #
    # No commit: this joins the caller's transaction, so the payment row and its
    # outbox event are written atomically. A failure to publish rolls back the
    # status change too, which is the correct pairing -- a payment silently
    # marked failed with nobody told is the outcome to avoid.
    await publish_domain_event(
        db=db,
        event=PaymentFailedEvent(
            event_type="PAYMENT_FAILED",

            schema_version=1,
            occurred_at=datetime.now(UTC).isoformat(),

            aggregate_type="payment",
            aggregate_id=payment.id,

            actor={
                "id": payment.patient_id,
                "role": UserRole.PATIENT.name,
            },

            causation_id=None,

            user_id=payment.patient_id,
            appointment_id=payment.appointment_id,
        ),
    )

    return payment