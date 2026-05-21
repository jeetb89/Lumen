# OlliveBird — LLM Inference Logging

A production-grade chatbot with a fully instrumented inference-logging pipeline. Every LLM call is timed, tokenised, costed, and written to ClickHouse in under 500 ms — without adding any latency to the response the user sees.

```
chat UI  →  FastAPI chatbot  →  OpenAI / Anthropic
                  │
           loglm SDK (in-process)
                  │ non-blocking queue
           Ingestion service  →  ClickHouse  →  Grafana
```

## Quickstart

```bash
git clone <repo>
cd OlliveBird

cp .env.example .env
# edit .env — add OPENAI_API_KEY and/or ANTHROPIC_API_KEY

docker compose -f infra/docker-compose.yml up
```

| Service | URL |
|---|---|
| Chat UI + API | http://localhost:8080 |
| Grafana dashboards | http://localhost:3000 |

Grafana opens in anonymous Viewer mode — no login required.

### Seed the dashboards

After the stack is up, send a burst of varied requests so the charts have something to show:

```bash
pip install httpx
python scripts/seed.py --requests 40
```

## Architecture

```
┌─────────────┐     SSE stream     ┌──────────────────────────────────────────┐
│  React/MUI  │ ◄────────────────► │  FastAPI chatbot  (port 8000 internal)   │
│  frontend   │                    │  ┌──────────────────────────────────────┐ │
└─────────────┘                    │  │  loglm SDK (in-process)              │ │
       │                           │  │  InferenceSpan  →  AsyncEmitter      │ │
  nginx gateway                    │  │  Queue(10 000)  →  batch POST        │ │
  (port 8080)                      │  └─────────────────────┬────────────────┘ │
                                   └────────────────────────│──────────────────┘
                                                            │ /v1/logs (batch)
                                   ┌────────────────────────▼──────────────────┐
                                   │  Ingestion service  (port 8001 internal)  │
                                   │  FastAPI  →  clickhouse-connect           │
                                   └────────────────────────┬──────────────────┘
                                                            │
                              ┌─────────────────────────────▼──────────────────┐
                              │  ClickHouse  (port 9000 native / 8123 HTTP)    │
                              │  inference_logs (MergeTree, 90-day TTL)        │
                              │  inference_minutely (AggregatingMergeTree)     │
                              │  inference_minutely_mv (Materialized View)     │
                              └─────────────────────────────┬──────────────────┘
                                                            │
                              ┌─────────────────────────────▼──────────────────┐
                              │  Grafana  (port 3000)                          │
                              │  grafana-clickhouse-datasource  →  5 panels    │
                              └────────────────────────────────────────────────┘

                              ┌────────────────────────────────────────────────┐
                              │  PostgreSQL  (port 5432 internal)              │
                              │  conversations, messages (transactional)       │
                              └────────────────────────────────────────────────┘
```

### Five tiers

| Tier | Technology | Role |
|---|---|---|
| Frontend | React + Vite + MUI | Streaming chat UI, model picker, conversation list |
| Chatbot | FastAPI + asyncpg | Multi-turn conversations, SSE streaming, multi-provider |
| Logging SDK | Pure Python (`loglm`) | Non-blocking span capture, async batched emit |
| Ingestion | FastAPI + clickhouse-connect | Validation, cost enrichment, ClickHouse writes |
| Storage | Postgres 16 + ClickHouse 24.8 | Transactional chat data + append-only analytics |

## Schema design

### PostgreSQL

```sql
conversations (id, user_id, title, status, model, provider, created_at, updated_at)
messages      (id, conversation_id, role, content, seq_num, created_at)
```

Postgres holds the source-of-truth chat data — mutable, ACID, served directly by the chatbot API. `seq_num` has a `UNIQUE (conversation_id, seq_num)` constraint so duplicate inserts fail fast rather than silently.

### ClickHouse

```sql
inference_logs      -- raw fact table, one row per LLM call
inference_minutely  -- AggregatingMergeTree rollup (quantileState / sum)
inference_minutely_mv -- materialized view that feeds the rollup on insert
```

**Why two databases?**
Postgres is optimised for point reads and small transactional writes — ideal for fetching a conversation's messages. ClickHouse is optimised for sequential scans across billions of rows with columnar compression — ideal for "p95 latency across all gpt-4o-mini calls in the last hour." Trying to do both in one system always means compromising one.

**`LowCardinality` on `provider`, `model`, `status`** — ClickHouse stores these as dictionary-encoded integers instead of raw strings, cutting storage by ~5× for those columns and making GROUP BY on them essentially free.

**Monthly partitioning + 90-day TTL** — partitions let ClickHouse drop old data by deleting whole directories rather than row-by-row. The TTL clause handles cleanup automatically.

**Materialized view for dashboard queries** — `quantileMerge` on the pre-aggregated `inference_minutely` table completes in milliseconds regardless of how many raw rows exist. Without it, a p95 query over a day of data would scan millions of rows on every dashboard refresh.

## Logging strategy

The SDK wraps every provider call in a `trace()` context manager:

```python
with trace(provider="openai", model="gpt-4o-mini", ...) as span:
    async for chunk in provider.stream(messages):
        span.record_chunk(chunk.delta)   # records TTFT on first call
        yield chunk
    span.record_response(text, finish_reason, tokens)
# span closes here — exactly one event emitted, always
```

The `finally` block guarantees emission whether the call succeeds, errors, or is cancelled. The emitted event goes onto an `asyncio.Queue(maxsize=10_000)` — enqueue is non-blocking and never stalls the response path.

A single background `asyncio.Task` drains the queue every 500 ms (or every 50 events), POSTs a batch to the ingestion service, and retries 5xx responses with exponential backoff. 4xx responses are dropped without retry. On overflow, the oldest event is dropped — recent data is more useful for debugging.

**PII redaction** — the SDK applies regex redaction (`[EMAIL]`, `[PHONE]`, `[SSN]`, `[CARD]`, `[APIKEY]`, `[JWT]`) to the 500-character `input_preview` and `output_preview` fields. Full content stays in Postgres unredacted.

## Failure modes

1. **LLM call succeeds, assistant-message insert fails.** The user sees an error; the model reply is lost; we've still billed for tokens. An outbox pattern would fix it; v1 accepts the risk.

2. **Ingest API returns 422 on a malformed event.** One bad event poisons its batch. The right fix is per-event validation at the API layer; v1 batches atomically.

3. **Client disconnect during streaming.** Detected via two paths: `request.is_disconnected()` poll (clean browser Stop-button path) and `asyncio.CancelledError` (TCP-RST / server-timeout path). Both paths persist the partial assistant text to Postgres before the span is emitted.

4. **SDK buffer overflow.** Drop-oldest; the `Emitter.dropped` counter is observable. No events lost silently.

5. **ClickHouse insert failure.** Ingest returns 503; SDK retries up to 3 times with backoff. Beyond that, events are dropped. A durable queue (Redis Streams) between ingest and ClickHouse would fix this.

## Tradeoffs

1. **Two databases.** Adds operational complexity but each does what it does best. A v0 in pure Postgres with a partitioned `inference_logs` table is defensible up to ~10 M rows/day.

2. **In-process SDK, not a sidecar.** Simpler for Python; doesn't generalise to other runtimes. A sidecar agent (OTel-collector style) would be the path for a polyglot stack.

3. **Regex-based PII redaction.** Catches obvious patterns; misses names and contextual identifiers. A real deployment would use a NER model or a dedicated redaction service.

4. **Cost computed at ingest, not on demand.** Dashboard queries are fast, but a price change doesn't reprice historical logs. A nightly backfill job would fix it.

5. **No message queue between ingest API and ClickHouse.** For this volume, the SDK's in-memory queue is sufficient. Redis Streams would buy durability across ingest restarts.

6. **No auth.** `user_id` defaults to `"anonymous"`. Adding auth requires session tokens and a users table — out of scope for v1.

## What I'd improve with more time

1. OpenTelemetry trace IDs threaded end-to-end so a single user request joins across frontend, chatbot, SDK, ingestion, and database.
2. A message queue (Redis Streams or Kafka) between ingest and ClickHouse for durability across restarts.
3. Per-event ingest validation so one bad event doesn't poison its batch.
4. Token-aware context window pruning instead of last-N-messages.
5. NER-based PII redaction with named-entity coverage.
6. Cost budgets with per-conversation spend alerts.
7. A thumbs-up/down feedback signal joined to the inference log for offline eval.
8. Replay tool that re-runs historical prompts against new models to compare quality.
9. Materialized view backfills via `INSERT INTO ... SELECT` for analytics on historical data.
10. Kubernetes manifests with resource limits and HPA on the ingestion service.

## Local development (without Docker)

```bash
# Start storage layer only
docker compose -f infra/docker-compose.yml up postgres clickhouse -d

# Run all three app services with hot reload
./run.sh
```

Services: chatbot → http://localhost:8000 · ingestion → http://localhost:8001 · frontend → http://localhost:5173

> The local postgres is exposed on port **5433** to avoid conflicting with a locally-installed Postgres instance.
