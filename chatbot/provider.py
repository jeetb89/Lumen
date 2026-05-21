import os
from dataclasses import dataclass
from openai import AsyncOpenAI

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_PROVIDER = "openai"
CONTEXT_WINDOW_TURNS = 10


@dataclass
class CompletionResult:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None


class OpenAIProvider:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    async def complete(
        self,
        messages: list[dict],
        model: str = DEFAULT_MODEL,
        system: str = "You are a helpful assistant.",
    ) -> CompletionResult:
        response = await self.client.chat.completions.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "system", "content": system}] + messages,
        )
        choice = response.choices[0]
        return CompletionResult(
            content=choice.message.content,
            model=response.model,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            finish_reason=choice.finish_reason,
        )


provider = OpenAIProvider()
