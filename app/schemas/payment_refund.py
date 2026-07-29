from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel, Field


class PaymentRefundRequest(BaseModel):
    amount: Decimal = Field(
        gt=0,
        description="Refund amount",
    )

    reason: str = Field(
        min_length=1,
        max_length=500,
    )


class PaymentRefundResponse(BaseModel):
    payment_id: int
    status: str
    refunded_amount: Decimal
    refund_transaction_id: str
    refunded_at: datetime