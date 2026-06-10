import time
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import (
    medicine_ai_failures_total,
    medicine_ai_latency_seconds,
    medicine_ai_requests_total,
    medicine_ai_tokens_total,
)

from app.integrations.openai_client import (
    OpenAIClient,
)

from app.services.medicine_context_service import (
    build_medicine_context,
)

from app.services.medicine_prompt_service import (
    build_prompt,
    PROMPT_VERSION,
)

from app.config import get_settings

from app.try_except.exceptions import (
    ServiceUnavailableError,
)

from app.services.medicine_ai_log_service import (
    create_ai_log,
)

from app.core.cache import get_cache,set_cache

from app.services.medicine_ai_guardrail_service import (
    validate_ai_response,
)
from app.services.medicine_ai_error_log_service import (
    create_ai_error_log,
)


MEDICAL_DISCLAIMER = (
    "\n\nMedical disclaimer: "
    "This information is educational and "
    "does not replace advice from a doctor, "
    "pharmacist, or other qualified "
    "healthcare professional."
)


class MedicineAIService:

    def __init__(self):

        self._client = None

    @property
    def client(self):

        if self._client is None:
            self._client = OpenAIClient()

        return self._client

    async def answer(
        self,
        db: AsyncSession,
        medicine,
        question: str,
    ) -> str:
        
        
        settings = get_settings()

        if not settings.ENABLE_MEDICINE_AI:
            raise ServiceUnavailableError(
                "Medicine AI is disabled"
            )

        medicine_ai_requests_total.inc()

        start = time.perf_counter()

        try:

            context = build_medicine_context(
                medicine
            )

            prompt = build_prompt(
                context=context,
                question=question,
            )

            normalized_question = " ".join(
                question.lower().strip().split()
            )

            cache_key = (
                f"medicine_ai_response:"
                f"{medicine.id}:"
                f"{normalized_question}"
            )

            cached = await get_cache(
                cache_key
            )

            if cached:
                return cached

            text, tokens = await self.client.generate(
                prompt
            )

            text = validate_ai_response(
                text
            )

            duration_ms = int(
                (
                    time.perf_counter()
                    - start
                )
                * 1000
            )

            await create_ai_log(
                db=db,
                medicine_id=medicine.id,
                medicine_name=medicine.name,
                question=question,
                answer=text,
                prompt_version=PROMPT_VERSION,
                tokens_used=tokens,
                latency_ms=duration_ms,
            )

            medicine_ai_tokens_total.inc(
                tokens
            )

            if not text.strip():

                return (
                    "No answer could be generated "
                    "from the medicine database."
                    f"{MEDICAL_DISCLAIMER}"
                )

            final_answer = (
                f"{text.strip()}"
                f"{MEDICAL_DISCLAIMER}"
            )

            await set_cache(
                cache_key,
                final_answer,
                ttl=86400,
            )

            return final_answer

        except Exception as exc:

            await create_ai_error_log(
                db=db,
                question=question,
                medicine_name=medicine.name,
                error=str(exc),
            )

            medicine_ai_failures_total.inc()

            raise

        finally:

            duration = (
                time.perf_counter()
                - start
            )

            medicine_ai_latency_seconds.observe(
                duration
            )