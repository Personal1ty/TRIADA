from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    @abstractmethod
    async def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        raise NotImplementedError
