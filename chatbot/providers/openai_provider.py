import os
from openai import AsyncOpenAI
from .base import StreamChunk


class OpenAIProvider:
    name = "openai"

    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    async def stream(self, messages, model, **params):
        response = await self.client.chat.completions.create(
            messages=messages,
            model=model,
            stream=True,
            stream_options={"include_usage": True},  # required for token counts in streaming
            max_tokens=params.get("max_tokens", 1024),
        )
        async for event in response:
            choice = event.choices[0] if event.choices else None
            delta = (choice.delta.content if choice and choice.delta else None) or ""
            finish = choice.finish_reason if choice else None
            usage = event.usage  # only set on the final chunk
            if delta or finish or usage:
                yield StreamChunk(
                    delta=delta,
                    finish_reason=finish,
                    prompt_tokens=usage.prompt_tokens if usage else None,
                    completion_tokens=usage.completion_tokens if usage else None,
                )
