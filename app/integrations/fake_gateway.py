"""In-process fake payment gateway for development / testing.

Mirrors ``BkashService`` so the whole payment flow (initiate → simulate page →
webhook → success → appointment confirmation) works without any real bKash
credentials. Selected via ``settings.PAYMENT_GATEWAY == "fake"``.

The ``create_payment`` step returns a ``bkashURL`` that points at an in-app
"simulate payment" page; the outcome for a payment can be flipped to failure via
``set_outcome`` (used by the dev-only endpoint) before the webhook fires.
"""

from decimal import Decimal
from uuid import uuid4

from app.config import get_settings

settings = get_settings()

# paymentID -> {"amount": str, "outcome": "success" | "failure"}
_STORE: dict[str, dict] = {}


def set_outcome(gateway_payment_id: str, outcome: str) -> bool:
    """Flip a fake payment's outcome. Returns False if it's unknown."""
    entry = _STORE.get(gateway_payment_id)
    if entry is None:
        return False
    entry["outcome"] = "failure" if outcome == "failure" else "success"
    return True


class FakePaymentGateway:
    async def create_payment(
        self,
        *,
        amount: Decimal,
        invoice_id: str,
    ) -> dict:
        payment_id = f"FAKE-{uuid4().hex}"
        _STORE[payment_id] = {"amount": str(amount), "outcome": "success"}
        return {
            "paymentID": payment_id,
            "bkashURL": f"{settings.FRONTEND_URL}/pay/simulate?paymentID={payment_id}",
        }

    async def execute_payment(
        self,
        *,
        gateway_payment_id: str,
    ) -> dict:
        entry = _STORE.get(gateway_payment_id, {"amount": "0", "outcome": "success"})
        if entry["outcome"] == "failure":
            return {"transactionStatus": "Failed"}
        return {
            "transactionStatus": "Completed",
            "trxID": f"TRX-{uuid4().hex[:12].upper()}",
            "amount": entry["amount"],
        }

    async def query_payment(
        self,
        *,
        gateway_payment_id: str,
    ) -> dict:
        entry = _STORE.get(gateway_payment_id)
        status = "Completed" if entry and entry["outcome"] == "success" else "Failed"
        return {"transactionStatus": status}

    async def refund_payment(
        self,
        *,
        gateway_payment_id: str,
        transaction_id: str,
        amount,
        reason: str,
    ) -> dict:
        return {
            "transactionStatus": "Completed",
            "refundTransactionId": f"REF-{uuid4().hex[:12].upper()}",
        }
