import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import httpx

from loglm.redaction import redact

log = logging.getLogger("loglm")

SCHEMA_VERSION = 1
PREVIEW_CHARS = int(os.environ.get("LOGLM_PREVIEW_CHARS", 500))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview(text: str | None) -> str | None:
    if text is None:
        return None
    return redact(text[:PREVIEW_CHARS])


# ---------------------------------------------------------------------------
# Span + context manager
# ---------------------------------------------------------------------------

class InferenceSpan:
    """Holds state for one LLM call. Mutated by the caller, emitted on exit."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        conversation_id: str,
        message_id: str | None = None,
        user_id: str = "anonymous",
        input_messages: list[dict] | None = None,
        params: dict | None = None,
    ):
        self.event_id = str(uuid.uuid4())
        self.started_at = _now_iso()
        self._t0 = time.perf_counter()

        self.provider = provider
        self.model = model
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.user_id = user_id

        last_user = next(
            (m["content"] for m in reversed(input_messages or []) if m["role"] == "user"),
            "",
        )
        self.input_preview = _preview(last_user)
        self.input_chars = len(last_user)
        self.num_messages = len(input_messages or [])
        self.params = params or {}

        self.output_text: str | None = None
        self.finish_reason: str | None = None
        self.prompt_tokens: int | None = None
        self.completion_tokens: int | None = None
        self.ttft_ms: int | None = None

        self._first_chunk_at: float | None = None

        self.status: str = "success"
        self.error: str | None = None

    def record_chunk(self, delta: str) -> None:
        """Call on each streaming chunk. Records TTFT on the first call."""
        if self._first_chunk_at is None and delta:
            self._first_chunk_at = time.perf_counter()
            self.ttft_ms = int((self._first_chunk_at - self._t0) * 1000)

    def record_response(
        self,
        *,
        text: str,
        finish_reason: str | None,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ):
        self.output_text = text
        self.finish_reason = finish_reason
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    def to_event(self) -> dict:
        latency_ms = int((time.perf_counter() - self._t0) * 1000)
        total = (
            self.prompt_tokens + self.completion_tokens
            if self.prompt_tokens is not None and self.completion_tokens is not None
            else None
        )
        return {
            "event_id": self.event_id,
            "schema_version": SCHEMA_VERSION,
            "timestamp": _now_iso(),
            "session": {
                "conversation_id": self.conversation_id,
                "message_id": self.message_id,
                "user_id": self.user_id,
            },
            "provider": self.provider,
            "model": self.model,
            "request": {
                "input_preview": self.input_preview,
                "input_chars": self.input_chars,
                "num_messages": self.num_messages,
                "params": self.params,
            },
            "response": {
                "output_preview": _preview(self.output_text),
                "output_chars": len(self.output_text) if self.output_text else 0,
                "finish_reason": self.finish_reason,
            },
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": total,
            },
            "timing": {
                "started_at": self.started_at,
                "ended_at": _now_iso(),
                "latency_ms": latency_ms,
                "ttft_ms": self.ttft_ms,
            },
            "status": self.status,
            "error": self.error,
        }


@contextmanager
def trace(**kwargs):
    """Wraps a provider call. Emits exactly one event on exit, always."""
    span = InferenceSpan(**kwargs)
    try:
        yield span
    except Exception as exc:
        span.status = "error"
        span.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        _emit(span.to_event())


# ---------------------------------------------------------------------------
# Async emitter — non-blocking, batched, retry on 5xx, drop-oldest on overflow
# ---------------------------------------------------------------------------

class Emitter:
    """Single background asyncio.Task that batches and POSTs events."""

    def __init__(
        self,
        *,
        url: str,
        max_queue: int = 10_000,
        batch_size: int = 50,
        flush_interval_s: float = 0.5,
        max_retries: int = 3,
    ):
        self.url = url
        self.max_queue = max_queue
        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s
        self.max_retries = max_retries

        self._queue: asyncio.Queue[dict] | None = None
        self._task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self._client: httpx.AsyncClient | None = None

        # Observable counters (wired to /metrics in stage 6)
        self.dropped = 0
        self.sent = 0
        self.failed = 0

    async def start(self):
        if self._task is not None:
            return
        self._queue = asyncio.Queue(maxsize=self.max_queue)
        self._stop = asyncio.Event()
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))
        self._task = asyncio.create_task(self._run(), name="loglm-emitter")

    async def stop(self):
        if self._stop:
            self._stop.set()
        if self._task:
            await self._task
        if self._client:
            await self._client.aclose()

    def emit(self, event: dict) -> None:
        """Non-blocking. Drops oldest event on queue overflow."""
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()   # drop oldest — recent events are more valuable
                self.dropped += 1
                self._queue.put_nowait(event)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                self.dropped += 1

    async def _run(self):
        batch: list[dict] = []
        while not self._stop.is_set():
            try:
                try:
                    first = await asyncio.wait_for(
                        self._queue.get(), timeout=self.flush_interval_s
                    )
                    batch.append(first)
                except asyncio.TimeoutError:
                    continue

                while len(batch) < self.batch_size:
                    try:
                        batch.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                await self._flush(batch)
                batch = []
            except Exception:
                log.exception("emitter loop error; discarding batch")
                batch = []

        # Final flush on shutdown — don't lose events on clean restart
        while self._queue:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch:
            await self._flush(batch)

    async def _flush(self, batch: list[dict]) -> None:
        payload = {"events": batch}
        backoff = 0.2
        for attempt in range(self.max_retries):
            try:
                resp = await self._client.post(self.url, json=payload)
                if resp.status_code < 300:
                    self.sent += len(batch)
                    return
                if 400 <= resp.status_code < 500:
                    log.warning("ingest rejected %d events: %s", len(batch), resp.text[:500])
                    self.failed += len(batch)
                    return  # don't retry 4xx — malformed event won't improve
            except httpx.HTTPError as exc:
                log.warning("ingest post failed (attempt %d): %s", attempt + 1, exc)
            await asyncio.sleep(backoff)
            backoff *= 2
        self.failed += len(batch)
        log.error("dropped %d events after %d retries", len(batch), self.max_retries)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_emitter: Emitter | None = None


def init(url: str | None = None, **kwargs: Any) -> Emitter:
    """Call once at application startup (inside the event loop)."""
    global _emitter
    if _emitter is not None:
        return _emitter
    _emitter = Emitter(
        url=url or os.environ.get("LOGLM_INGEST_URL", "http://localhost:8001/v1/logs"),
        **kwargs,
    )
    return _emitter


def get_emitter() -> Emitter:
    if _emitter is None:
        raise RuntimeError("loglm.init() must be called before use")
    return _emitter


def _emit(event: dict) -> None:
    """Called from trace() finally block. Non-blocking."""
    if _emitter is None:
        print(json.dumps(event), flush=True)
        return
    _emitter.emit(event)
