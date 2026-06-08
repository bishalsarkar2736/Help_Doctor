import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.idempotency_key import IdempotencyKey
from sqlalchemy.exc import IntegrityError



def create_request_hash(body: dict) -> str:
    body_str = json.dumps(body, sort_keys=True)
    return hashlib.sha256(body_str.encode()).hexdigest()


async def get_existing_key(
    db: AsyncSession,
    key: str,
    user_id: int,
):
    result = await db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.key == key,
            IdempotencyKey.user_id == user_id,
        )
        .with_for_update()
    )

    return result.scalar_one_or_none()


async def store_key(
    db: AsyncSession,
    key: str,
    user_id: int,
    request_hash: str,
):
    record = IdempotencyKey(
        key=key,
        user_id=user_id,
        request_hash=request_hash,
    )

    db.add(record)

    try:
        await db.flush()

    except IntegrityError:
        # 🔥 Someone else inserted first
        result = await db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.key == key,
                IdempotencyKey.user_id == user_id,
            )
        )
        record = result.scalar_one()

    return record


async def save_response(
    db: AsyncSession,
    record: IdempotencyKey,
    response_body: dict,
    status_code: int,
):
    record.response_body = response_body
    record.status_code = status_code

    await db.flush()