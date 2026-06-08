import time

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
)

from app.utils.ai_retry import (
    with_ai_retry,
)


class MedicineAIService:

    def __init__(self):

        self.client = OpenAIClient()

    async def answer(
        self,
        medicine,
        question: str,
    ) -> str:

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

            text, tokens = await with_ai_retry(
                lambda: self.client.generate(
                    prompt
                )
            )

            medicine_ai_tokens_total.inc(
                tokens
            )

            return text

        except Exception:

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