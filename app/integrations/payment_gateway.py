from abc import ABC, abstractmethod


class PaymentGateway(ABC):

    @abstractmethod
    async def create_payment(self, amount: float, invoice_id: str):
        pass

    @abstractmethod
    async def verify_payment(self, payment_id: str):
        pass