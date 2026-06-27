from abc import ABC, abstractmethod
from decimal import Decimal

class PaymentGateway(ABC):

    @abstractmethod
    async def create_payment(
        self,
        *,
        amount: Decimal,
        invoice_id: str,
        payer_reference: str | None = None,
        callback_url: str | None = None,
    ) -> dict:
        pass

    @abstractmethod
    async def execute_payment(
        self,
        *,
        gateway_payment_id: str,
    ) -> dict:
        pass

    @abstractmethod
    async def query_payment(
        self,
        *,
        gateway_payment_id: str,
    ) -> dict:
        pass

    @abstractmethod
    async def refund_payment(
        self,
        *,
        transaction_id: str,
        amount: Decimal,
    ) -> dict:
        pass