# from sqlalchemy.ext.asyncio import AsyncSession

# from app.services.notification_service import (
#     notify_user,
# )

# from app.schemas.event import (
#     PaymentSuccessEvent,
# )


# async def handle_payment_success(
#     *,
#     db: AsyncSession,
#     validated: PaymentSuccessEvent,
#     event_id,
# ):

#     await notify_user(
#         db=db,
#         user_id=validated.user_id,
#         title="Payment Successful",
#         message="Your payment was successful",
#         appointment_id=validated.appointment_id,
#         event_id=event_id,
#     )