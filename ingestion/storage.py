import json
import os

import clickhouse_connect

from models import InferenceEvent
from enrichment import compute_cost, compute_throughput

_client = None

COLUMNS = [
    "event_id", "schema_version", "event_timestamp",
    "conversation_id", "message_id", "user_id",
    "provider", "model",
    "input_preview", "input_chars", "num_messages", "params",
    "output_preview", "output_chars", "finish_reason",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "started_at", "ended_at", "latency_ms", "ttft_ms",
    "status", "error",
    "cost_usd", "tokens_per_second",
]


async def get_client():
    global _client
    if _client is None:
        _client = await clickhouse_connect.get_async_client(
            host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
            port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
            username=os.environ.get("CLICKHOUSE_USER", "loglm"),
            password=os.environ.get("CLICKHOUSE_PASSWORD", "loglm"),
            database=os.environ.get("CLICKHOUSE_DB", "loglm"),
        )
    return _client


def _to_row(e: InferenceEvent) -> list:
    cost = compute_cost(
        e.provider, e.model, e.usage.prompt_tokens, e.usage.completion_tokens
    )
    tps = compute_throughput(
        e.usage.completion_tokens, e.timing.latency_ms, e.timing.ttft_ms
    )
    return [
        e.event_id, e.schema_version, e.timestamp,
        e.session.conversation_id, e.session.message_id, e.session.user_id,
        e.provider, e.model,
        e.request.input_preview or "", e.request.input_chars,
        e.request.num_messages, json.dumps(e.request.params),
        e.response.output_preview or "", e.response.output_chars,
        e.response.finish_reason,
        e.usage.prompt_tokens, e.usage.completion_tokens, e.usage.total_tokens,
        e.timing.started_at, e.timing.ended_at,
        e.timing.latency_ms, e.timing.ttft_ms,
        e.status, e.error,
        cost, tps,
    ]


async def insert_events(events: list[InferenceEvent]) -> int:
    if not events:
        return 0
    rows = [_to_row(e) for e in events]
    client = await get_client()
    await client.insert("inference_logs", rows, column_names=COLUMNS)
    return len(rows)
