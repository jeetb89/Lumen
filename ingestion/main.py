import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from models import IngestBatch, IngestResponse, InferenceEvent
from storage import get_client, insert_events

log = logging.getLogger("ingest")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_client()  # fail fast if ClickHouse is misconfigured
    yield


app = FastAPI(title="OlliveBird Ingestion", lifespan=lifespan)


@app.post("/v1/logs", response_model=IngestResponse)
async def ingest_batch(batch: IngestBatch) -> IngestResponse:
    if not batch.events:
        return IngestResponse(accepted=0)
    try:
        n = await insert_events(batch.events)
    except Exception as exc:
        log.exception("clickhouse insert failed")
        raise HTTPException(status_code=503, detail=str(exc))
    return IngestResponse(accepted=n)


@app.post("/v1/logs/single", response_model=IngestResponse)
async def ingest_single(event: InferenceEvent) -> IngestResponse:
    """Backwards-compatible single-event endpoint for stage 3 SDK."""
    return await ingest_batch(IngestBatch(events=[event]))


@app.get("/healthz")
async def healthz():
    return {"ok": True}
