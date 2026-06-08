from app.core.celery import celery_app
from app.task.base import run_async
from app.services.slot_generation import generate_slots


@celery_app.task(name="app.tasks.slot_generation.generate_slots_task")
@run_async
async def generate_slots_task():
    await generate_slots()