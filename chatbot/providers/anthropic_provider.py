import os
import anthropic
from .base import StreamChunk


class AnthropicProvider:
    name = "anthropic"

    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    async def stream(self, messages, model, **params):
        # Anthropic takes system as a separate param; OpenAI puts it in the messages list
        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        non_system = [m for m in messages if m["role"] != "system"]

        input_tokens = output_tokens = None
        async with self.client.messages.stream(
            model=model,
            system=system,
            messages=non_system,
            max_tokens=params.get("max_tokens", 1024),
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    yield StreamChunk(delta=event.delta.text)
                elif event.type == "message_delta" and event.usage:
                    output_tokens = event.usage.output_tokens
                elif event.type == "message_start":
                    input_tokens = event.message.usage.input_tokens

            final = await stream.get_final_message()
            yield StreamChunk(
                delta="",
                finish_reason=final.stop_reason,
                prompt_tokens=input_tokens or final.usage.input_tokens,
                completion_tokens=output_tokens or final.usage.output_tokens,
            )
