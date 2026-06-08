from abc import ABC, abstractmethod


class AIClient(ABC):

    @abstractmethod
    async def generate(
        self,
        prompt: str,
    ) -> str:
        pass