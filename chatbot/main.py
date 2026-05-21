import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

import loglm
from loglm import trace
from db import init_pool, close_pool, get_db, get_pool
from providers import setup as setup_providers, get_provider, list_providers
from providers.base import DEFAULT_MODEL, DEFAULT_PROVIDER, CONTEXT_WINDOW_TURNS

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    setup_providers()         # after load_dotenv so env vars are available
    emitter = loglm.init()
    await emitter.start()
    yield
    await emitter.stop()
    await close_pool()


app = FastAPI(title="OlliveBird", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Schemas ---

class CreateConvRequest(BaseModel):
    user_id: str = "anonymous"
    title: str | None = None
    model: str = DEFAULT_MODEL
    provider: str = DEFAULT_PROVIDER


class SendMessageRequest(BaseModel):
    content: str
    system: str = "You are a helpful assistant."


# --- SSE helper ---

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# --- Endpoints ---

@app.get("/api/providers")
async def get_providers():
    return list_providers()


@app.post("/api/conversations", status_code=201)
async def create_conversation(body: CreateConvRequest, db=Depends(get_db)):
    conv_id = await db.fetchval(
        """INSERT INTO conversations (user_id, title, model, provider)
           VALUES ($1, $2, $3, $4) RETURNING id""",
        body.user_id, body.title, body.model, body.provider,
    )
    return {"id": str(conv_id)}


@app.get("/api/conversations")
async def list_conversations(user_id: str = "anonymous", limit: int = 50, db=Depends(get_db)):
    rows = await db.fetch(
        """SELECT id, title, status, updated_at,
             (SELECT content FROM messages
              WHERE conversation_id = c.id ORDER BY seq_num DESC LIMIT 1) AS last_message
           FROM conversations c
           WHERE user_id = $1
           ORDER BY updated_at DESC LIMIT $2""",
        user_id, limit,
    )
    return [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "status": r["status"],
            "updated_at": r["updated_at"].isoformat(),
            "last_message": r["last_message"],
        }
        for r in rows
    ]


@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str, db=Depends(get_db)):
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid conversation_id")

    rows = await db.fetch(
        """SELECT id, role, content, seq_num, created_at
           FROM messages WHERE conversation_id = $1 ORDER BY seq_num""",
        conv_uuid,
    )
    return [
        {
            "id": str(r["id"]),
            "role": r["role"],
            "content": r["content"],
            "seq_num": r["seq_num"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@app.post("/api/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    request: Request,
    db=Depends(get_db),
):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content cannot be empty")

    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid conversation_id")

    # Transaction 1: lock, validate, compute seq_num, persist user message, load history
    async with db.transaction():
        conv = await db.fetchrow(
            "SELECT model, provider, status, title FROM conversations WHERE id = $1 FOR UPDATE",
            conv_uuid,
        )
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        if conv["status"] != "active":
            raise HTTPException(status_code=409, detail="conversation is not active")

        next_seq = await db.fetchval(
            "SELECT COALESCE(MAX(seq_num), 0) + 1 FROM messages WHERE conversation_id = $1",
            conv_uuid,
        )

        if next_seq == 1 and conv["title"] is None:
            await db.execute(
                "UPDATE conversations SET title = $1 WHERE id = $2",
                body.content[:50], conv_uuid,
            )

        user_msg_id = await db.fetchval(
            """INSERT INTO messages (conversation_id, role, content, seq_num)
               VALUES ($1, 'user', $2, $3) RETURNING id""",
            conv_uuid, body.content, next_seq,
        )

        history_rows = await db.fetch(
            """SELECT role, content FROM messages
               WHERE conversation_id = $1 ORDER BY seq_num DESC LIMIT $2""",
            conv_uuid, CONTEXT_WINDOW_TURNS * 2,
        )
        history = [{"role": r["role"], "content": r["content"]} for r in reversed(history_rows)]

    # System prompt prepended here; adapters normalise it per-provider
    messages_for_llm = [{"role": "system", "content": body.system}] + history

    prov = get_provider(conv["provider"] or DEFAULT_PROVIDER)

    async def _save_assistant(cid: uuid.UUID, text: str, seq: int) -> None:
        """Persist a partial or complete assistant message. Used by both normal and cancel paths."""
        try:
            async with get_pool().acquire() as conn:
                async with conn.transaction():
                    await conn.fetchval(
                        """INSERT INTO messages (conversation_id, role, content, seq_num)
                           VALUES ($1, 'assistant', $2, $3) RETURNING id""",
                        cid, text, seq,
                    )
                    await conn.execute(
                        "UPDATE conversations SET updated_at = now() WHERE id = $1", cid
                    )
        except Exception:
            pass  # best-effort; data was already logged to ClickHouse

    async def event_generator():
        full_text_parts: list[str] = []
        finish_reason: str | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None

        with trace(
            provider=conv["provider"] or DEFAULT_PROVIDER,
            model=conv["model"],
            conversation_id=str(conv_uuid),
            message_id=str(user_msg_id),
            user_id="anonymous",
            input_messages=messages_for_llm,
            params={"max_tokens": 1024},
        ) as span:
            try:
                async for chunk in prov.stream(
                    messages_for_llm, model=conv["model"], max_tokens=1024
                ):
                    # Poll for disconnect before handing tokens to the client
                    if await request.is_disconnected():
                        span.status = "cancelled"
                        break
                    if chunk.delta:
                        span.record_chunk(chunk.delta)
                        full_text_parts.append(chunk.delta)
                        yield _sse("delta", {"text": chunk.delta})
                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason
                    if chunk.prompt_tokens is not None:
                        prompt_tokens = chunk.prompt_tokens
                        completion_tokens = chunk.completion_tokens
            except asyncio.CancelledError:
                # Starlette cancels the generator when the client disconnects mid-stream.
                # Schedule partial-text persistence as an independent task before re-raising,
                # so it survives this cancellation. The `done` SSE won't be sent in this path.
                span.status = "cancelled"
                partial = "".join(full_text_parts)
                if partial:
                    asyncio.ensure_future(_save_assistant(conv_uuid, partial, next_seq + 1))
                raise
            finally:
                # Span must close before persistence so latency_ms excludes the DB write
                span.record_response(
                    text="".join(full_text_parts),
                    finish_reason=finish_reason
                    or ("cancelled" if span.status == "cancelled" else None),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )

        # Persist assistant message after the span has closed (clean path: is_disconnected()
        # break OR normal completion).
        full_text = "".join(full_text_parts)
        assistant_msg_id = None
        if full_text:
            await _save_assistant(conv_uuid, full_text, next_seq + 1)
            # Fetch the ID we just inserted so the `done` event can reference it
            async with get_pool().acquire() as conn:
                assistant_msg_id = await conn.fetchval(
                    "SELECT id FROM messages WHERE conversation_id=$1 AND seq_num=$2",
                    conv_uuid, next_seq + 1,
                )

        yield _sse("done", {
            "finish_reason": finish_reason,
            "assistant_message_id": str(assistant_msg_id) if assistant_msg_id else None,
        })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}
