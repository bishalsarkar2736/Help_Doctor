from openai import AsyncOpenAI

from app.config import get_settings


class OpenAIClient:

    def __init__(self):

        self.client = AsyncOpenAI(
            api_key=get_settings().OPENAI_API_KEY,
        )

    async def generate(
        self,
        prompt: str,
    ) -> tuple[str, int]:

        response = await self.client.responses.create(
            model=get_settings().OPENAI_MODEL,
            input=prompt,
        )

        text = response.output_text

        tokens = (
            response.usage.total_tokens
            if response.usage
            else 0
        )

        return text, tokens