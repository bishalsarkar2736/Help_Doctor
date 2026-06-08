from pydantic import BaseModel, Field


class BkashWebhookSchema(BaseModel):

    paymentID: str = Field(min_length=3)