# loglm SDK

Wraps a single LLM call and emits one structured log event on exit — whether the call succeeds, errors, or is cancelled.

## Usage

```python
from loglm import trace

with trace(
    provider="openai",
    model="gpt-4o-mini",
    conversation_id="<uuid>",
    message_id="<uuid>",      # the user message that triggered this call
    user_id="anonymous",
    input_messages=[...],     # full message list sent to the model
    params={"max_tokens": 1024},
) as span:
    result = await provider.complete(...)
    span.record_response(
        text=result.content,
        finish_reason=result.finish_reason,
        prompt_tokens=result.input_tokens,
        completion_tokens=result.output_tokens,
    )
```

One event is always emitted: the `finally` block fires on success, exception, and cancellation. The SDK never swallows exceptions — it observes, records status, and re-raises.

## Event schema (v1)

```json
{
  "event_id": "uuid4 — generated client-side for idempotent ingestion",
  "schema_version": 1,
  "timestamp": "2026-05-21T14:32:01.234Z",

  "session": {
    "conversation_id": "uuid",
    "message_id": "uuid",
    "user_id": "anonymous"
  },

  "provider": "openai",
  "model": "gpt-4o-mini",

  "request": {
    "input_preview": "first 500 chars of last user message",
    "input_chars": 27,
    "num_messages": 4,
    "params": {"max_tokens": 1024}
  },

  "response": {
    "output_preview": "first 500 chars of reply",
    "output_chars": 142,
    "finish_reason": "stop"
  },

  "usage": {
    "prompt_tokens": 87,
    "completion_tokens": 24,
    "total_tokens": 111
  },

  "timing": {
    "started_at": "ISO8601",
    "ended_at": "ISO8601",
    "latency_ms": 1657,
    "ttft_ms": null
  },

  "status": "success",
  "error": null
}
```

`status` is one of: `success | error | cancelled | timeout`

`ttft_ms` is always `null` until stage 5 adds streaming support. The field is present now so the ingestion schema doesn't need to change.

`event_id` is a client-generated UUID4. The ingestion service uses `INSERT ... ON CONFLICT DO NOTHING` so retries are safe.

Full content lives in the `messages` table from stage 2. Previews here are for dashboard searchability only.

## Configuration

| Env var | Default | Description |
|---|---|---|
| `LOGLM_INGEST_URL` | `http://localhost:8001/v1/logs` | Ingestion service endpoint |
| `LOGLM_PREVIEW_CHARS` | `500` | Max chars for input/output previews |

## Known limitations (fixed in stage 4)

- `_emit` is synchronous and blocks the calling coroutine for up to 2s on timeout
- No batching — one event per HTTP request
- No retries — falls back to stdout on any failure
