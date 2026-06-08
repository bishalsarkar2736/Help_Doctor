from fastapi import Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.idempotency_service import (
    get_existing_key,
    create_request_hash,
    store_key,
)

async def handle_idempotency(
    request: Request,
    db: AsyncSession,
    user_id: int,
    idempotency_key: str | None = Header(default=None),
):
    if not idempotency_key:
        return None

    body = await request.json()

    request_hash = create_request_hash(body)

    existing = await get_existing_key(db, idempotency_key, user_id)

    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=400,
                detail="Idempotency key reused with different request",
            )

        if existing.response_body:
            return existing

    record = await store_key(
        db,
        idempotency_key,
        user_id,
        request_hash,
    )

    return record