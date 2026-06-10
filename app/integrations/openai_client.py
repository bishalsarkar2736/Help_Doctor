from openai import AsyncOpenAI

from app.config import get_settings
from app.try_except.exceptions import ConfigurationError
from app.utils.ai_retry import with_ai_retry


class OpenAIClient:

    def __init__(self):

        settings = get_settings()

        if not settings.OPENAI_API_KEY:
            raise ConfigurationError(
                "OPENAI_API_KEY is not configured"
            )

        self.model = settings.OPENAI_MODEL

        self.client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=30.0,
        )

    async def generate(
        self,
        prompt: str,
    ) -> tuple[str, int]:

        async def _call() -> tuple[str, int]:

            response = (
                await self.client.responses.create(
                    model=self.model,
                    input=prompt,
                )
            )

            text = response.output_text

            tokens = (
                response.usage.total_tokens
                if response.usage
                else 0
            )

            return text, tokens

        return await with_ai_retry(_call)