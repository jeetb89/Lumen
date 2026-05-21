from dataclasses import dataclass
from typing import AsyncIterator, Protocol

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_PROVIDER = "openai"
CONTEXT_WINDOW_TURNS = 10


@dataclass
class StreamChunk:
    delta: str
    finish_reason: str | None = None
    # Populated only on the final chunk
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Provider(Protocol):
    name: str

    async def stream(
        self,
        messages: list[dict],
        model: str,
        **params,
    ) -> AsyncIterator[StreamChunk]: ...
