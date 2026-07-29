"""Selects the active payment gateway from settings.

``PAYMENT_GATEWAY=fake`` uses the in-process :class:`FakePaymentGateway`
(dev/test simulate flow); anything else uses the real bKash integration.
"""

from app.config import get_settings
from app.integrations.bkash.bkash_service import BkashService
from app.integrations.fake_gateway import FakePaymentGateway

settings = get_settings()


def get_payment_gateway():
    if settings.PAYMENT_GATEWAY == "fake":
        return FakePaymentGateway()
    return BkashService()
