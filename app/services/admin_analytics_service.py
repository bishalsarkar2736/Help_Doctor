from datetime import timedelta
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.doctor_slot import DoctorSlot
from app.models.notification import Notification
from app.services.clinic_context_service import (
    get_current_clinic,
)




async def get_dashboard_overview(db: AsyncSession):
    """
    High-level system stats
    """

    clinic = await get_current_clinic(db)


    total_appointments = await db.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.clinic_id == clinic.id
        )
    )

    status_counts = await db.execute(
        select(
            Appointment.status,
            func.count()
        )
        .where(
            Appointment.clinic_id
            == clinic.id
        )
        .group_by(
            Appointment.status
        )
    )

    status_map = {
        status.value: count
        for status, count in status_counts.all()
    }

    total_doctors = await db.scalar(
        select(func.count())
        .select_from(Doctor)
        .where(
            Doctor.clinic_id == clinic.id
        )
    )

    return {
        "total_appointments": total_appointments,
        "total_doctors": total_doctors,
        "status_breakdown": status_map,
    }


async def get_daily_appointments(db: AsyncSession, days: int = 7):
    """
    Daily appointment trend
    """

    clinic = await get_current_clinic(db)


    since = utc_now() - timedelta(days=days)

    result = await db.execute(
        select(
            func.date(Appointment.scheduled_at),
            func.count()
        )
        .where(
            Appointment.scheduled_at >= since,
            Appointment.clinic_id== clinic.id,
        )
        .group_by(func.date(Appointment.scheduled_at))
        .order_by(func.date(Appointment.scheduled_at))
    )

    return [
        {
            "date": str(row[0]),
            "count": row[1],
        }
        for row in result.all()
    ]


async def get_top_doctors_by_appointments(db: AsyncSession, limit: int = 5):
    """
    Doctors with most appointments
    """

    clinic = await get_current_clinic(db)


    result = await db.execute(
        select(
            Doctor.id,
            func.count(Appointment.id).label("total")
        )
        .join(Appointment, Appointment.doctor_id == Doctor.id)
        .where(
            Doctor.clinic_id
            == clinic.id,

            Appointment.clinic_id
            == clinic.id,
        )
        .group_by(Doctor.id)
        .order_by(func.count(Appointment.id).desc())
        .limit(limit)
    )

    return [
        {
            "doctor_id": row[0],
            "appointments": row[1],
        }
        for row in result.all()
    ]



async def get_no_show_analytics(
    *,
    db: AsyncSession,
):
    clinic = await get_current_clinic(db)

    total_confirmed = await db.scalar(
        select(
            func.count(Appointment.id)
        ).where(
            Appointment.clinic_id == clinic.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
    )

    total_no_show = await db.scalar(
        select(
            func.count(Appointment.id)
        ).where(
            Appointment.clinic_id == clinic.id,
            Appointment.status == AppointmentStatus.NO_SHOW,
        )
    )

    total_confirmed = total_confirmed or 0
    total_no_show = total_no_show or 0

    if total_confirmed == 0:
        rate = 0.0
    else:
        rate = round(
            (total_no_show / total_confirmed) * 100,
            2,
        )

    return {
        "total_confirmed": total_confirmed,
        "total_no_show": total_no_show,
        "no_show_rate": rate,
    }


async def get_cancellation_analytics(
    *,
    db: AsyncSession,
):
    clinic = await get_current_clinic(db)

    total_appointments = await db.scalar(
        select(
            func.count(Appointment.id)
        )
        .where(
            Appointment.clinic_id == clinic.id
        )
    )

    cancelled_appointments = await db.scalar(
        select(
            func.count(Appointment.id)
        )
        .where(
            Appointment.clinic_id == clinic.id,
            Appointment.status
            == AppointmentStatus.CANCELLED,
        )
    )

    total_appointments = (
        total_appointments or 0
    )

    cancelled_appointments = (
        cancelled_appointments or 0
    )

    if total_appointments == 0:
        rate = 0.0
    else:
        rate = round(
            (
                cancelled_appointments
                / total_appointments
            ) * 100,
            2,
        )

    return {
        "total_appointments":
            total_appointments,

        "cancelled_appointments":
            cancelled_appointments,

        "cancellation_rate":
            rate,
    }


async def get_doctor_utilization(db, doctor_id: int):

    clinic = await get_current_clinic(db)


    total_slots = await db.scalar(
        select(func.count())
        .select_from(DoctorSlot)
        .join(
            Doctor,
            Doctor.id == DoctorSlot.doctor_id,
        )
        .where(
            DoctorSlot.doctor_id == doctor_id,
            Doctor.clinic_id == clinic.id,
        )
    )

    booked_slots = await db.scalar(
        select(func.count())
        .select_from(DoctorSlot)
        .join(
            Doctor,
            Doctor.id == DoctorSlot.doctor_id,
        )
        .where(
            DoctorSlot.doctor_id == doctor_id,
            Doctor.clinic_id == clinic.id,
            DoctorSlot.is_booked.is_(True),
        )
    )

    if not total_slots:
        return {
            "doctor_id": doctor_id,
            "utilization": 0
        }

    return {
        "doctor_id": doctor_id,
        "utilization": round(booked_slots / total_slots, 4)
    }


async def get_system_utilization(db):

    clinic = await get_current_clinic(db)


    total_slots = await db.scalar(
        select(func.count())
        .select_from(DoctorSlot)
        .join(
            Doctor,
            Doctor.id == DoctorSlot.doctor_id,
        )
        .where(
            Doctor.clinic_id == clinic.id,
        )
    )

    booked_slots = await db.scalar(
        select(func.count())
        .select_from(DoctorSlot)
        .join(
            Doctor,
            Doctor.id == DoctorSlot.doctor_id,
        )
        .where(
            Doctor.clinic_id == clinic.id,
            DoctorSlot.is_booked.is_(True),
        )
    )

    if not total_slots:
        return {"utilization": 0}

    return {
        "utilization": round(booked_slots / total_slots, 4)
    }


async def get_notification_analytics(
    db: AsyncSession,
):
    total_notifications = await db.scalar(
        select(func.count(Notification.id))
    )

    push_delivered = await db.scalar(
        select(func.count(Notification.id))
        .where(
            Notification.push_delivered_at.is_not(None)
        )
    )

    email_delivered = await db.scalar(
        select(func.count(Notification.id))
        .where(
            Notification.email_delivered_at.is_not(None)
        )
    )

    failed = await db.scalar(
        select(func.count(Notification.id))
        .where(
            Notification.delivery_failed_at.is_not(None)
        )
    )

    total_notifications = total_notifications or 0
    push_delivered = push_delivered or 0
    email_delivered = email_delivered or 0
    failed = failed or 0

    return {
        "total_notifications": total_notifications,
        "push_delivered": push_delivered,
        "email_delivered": email_delivered,
        "failed": failed,
        "push_success_rate": round(
            (push_delivered / total_notifications) * 100,
            2,
        ) if total_notifications else 0,
        "email_success_rate": round(
            (email_delivered / total_notifications) * 100,
            2,
        ) if total_notifications else 0,
        "failure_rate": round(
            (failed / total_notifications) * 100,
            2,
        ) if total_notifications else 0,
    }


async def get_daily_notification_volume(
    db: AsyncSession,
):
    result = await db.execute(
        select(
            func.date(Notification.created_at),
            func.count(Notification.id),
        )
        .group_by(
            func.date(Notification.created_at)
        )
        .order_by(
            func.date(Notification.created_at)
        )
    )

    return [
        {
            "date": str(day),
            "count": count,
        }
        for day, count in result.all()
    ]