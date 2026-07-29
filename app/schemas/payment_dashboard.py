from decimal import Decimal

from pydantic import BaseModel


class PaymentDashboardResponse(BaseModel):

    total_payments: int

    successful_payments: int

    total_payment_amount: Decimal

    refund_count: int

    total_refunded_amount: Decimal

    refund_rate: float