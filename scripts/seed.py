#!/usr/bin/env python3
"""
Seed the chatbot with a varied set of requests so the Grafana dashboards
have meaningful curves when you first demo the project.

Usage:
    python scripts/seed.py [--base-url http://localhost:8080] [--requests 40]

The seeder:
  - Creates several conversations across available models
  - Sends a mix of short and long prompts
  - Sprinkles in deliberate cancellations (stop after first few tokens)
  - Fires one request to a nonexistent model to seed an error row
  - Prints a live progress line and a final summary
"""

import argparse
import asyncio
import json
import random
import sys
import time

import httpx

PROMPTS = [
    "What is latency in distributed systems?",
    "Explain the CAP theorem in one paragraph.",
    "Write a haiku about database indexes.",
    "What is the difference between p50 and p99 latency?",
    "Name three benefits of columnar storage.",
    "What is a materialized view and when would you use one?",
    "Explain eventual consistency in simple terms.",
    "Write a one-sentence description of ClickHouse.",
    "What is backpressure in streaming systems?",
    "Give an example of a good use case for Redis Streams.",
    "What does TTFT stand for in LLM inference?",
    "Explain the tradeoff between batch size and latency.",
    "What is token-per-second throughput?",
    "Why is PII redaction important in analytics pipelines?",
    "Describe the drop-oldest queue strategy in one sentence.",
    "Write a Python function that retries with exponential backoff.",
    "What is a hot partition in a time-series database?",
    "What is the difference between a fact table and a dimension table?",
    "Explain why SSE is preferred over WebSockets for one-way streaming.",
    "What is a two-phase commit and when should you avoid it?",
]

LONG_PROMPT = (
    "Write a detailed 300-word essay on the history of distributed databases, "
    "covering key milestones from Google Bigtable through modern systems like ClickHouse."
)

MODELS = [
    ("openai", "gpt-4o-mini"),
    ("openai", "gpt-4o-mini"),
    ("openai", "gpt-4o-mini"),  # weighted towards cheapest
]


def pick_model():
    return random.choice(MODELS)


async def create_conversation(client: httpx.AsyncClient, base_url: str, provider: str, model: str) -> str:
    r = await client.post(
        f"{base_url}/api/conversations",
        json={"provider": provider, "model": model},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["id"]


async def send_and_drain(
    client: httpx.AsyncClient,
    base_url: str,
    conv_id: str,
    prompt: str,
    cancel_after_chunks: int = 0,
) -> dict:
    """Stream a message. If cancel_after_chunks > 0, abort after that many delta events."""
    chunks = 0
    finish_reason = None
    cancelled = False
    t0 = time.perf_counter()

    try:
        async with client.stream(
            "POST",
            f"{base_url}/api/conversations/{conv_id}/messages",
            json={"content": prompt},
            timeout=httpx.Timeout(60.0, connect=5.0),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("event: delta"):
                    chunks += 1
                    if cancel_after_chunks and chunks >= cancel_after_chunks:
                        cancelled = True
                        break
                elif line.startswith("data:") and '"finish_reason"' in line:
                    try:
                        finish_reason = json.loads(line[5:]).get("finish_reason")
                    except json.JSONDecodeError:
                        pass
    except (httpx.RemoteProtocolError, httpx.ReadError):
        pass  # expected when we abort early

    return {
        "chunks": chunks,
        "finish_reason": "cancelled" if cancelled else finish_reason,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


async def seed_error(client: httpx.AsyncClient, base_url: str):
    """Send one request to a nonexistent model to produce an error log row."""
    try:
        conv_id = await create_conversation(client, base_url, "openai", "gpt-99-nonexistent")
        await client.post(
            f"{base_url}/api/conversations/{conv_id}/messages",
            json={"content": "ping"},
            timeout=15,
        )
    except Exception:
        pass


async def run(base_url: str, total: int):
    results = {"success": 0, "cancelled": 0, "error": 0}
    completed = 0

    async with httpx.AsyncClient() as client:
        # Health check
        try:
            r = await client.get(f"{base_url}/api/health", timeout=5)
            r.raise_for_status()
        except Exception as exc:
            print(f"ERROR: chatbot not reachable at {base_url} — {exc}")
            print("Start the stack first: docker compose -f infra/docker-compose.yml up")
            sys.exit(1)

        print(f"Seeding {total} requests against {base_url} …\n")

        tasks = []
        for i in range(total):
            provider, model = pick_model()
            prompt = LONG_PROMPT if i % 8 == 7 else random.choice(PROMPTS)
            cancel = random.randint(3, 8) if i % 7 == 6 else 0  # ~1 in 7 cancelled
            tasks.append((provider, model, prompt, cancel))

        # One deliberate error
        await seed_error(client, base_url)

        for i, (provider, model, prompt, cancel) in enumerate(tasks):
            try:
                conv_id = await create_conversation(client, base_url, provider, model)
                result = await send_and_drain(client, base_url, conv_id, prompt, cancel)
                status = result["finish_reason"] or "success"
                results[status if status in results else "success"] += 1
            except Exception as exc:
                results["error"] += 1
                status = f"err({exc})"

            completed += 1
            bar = "█" * (completed * 30 // total) + "░" * (30 - completed * 30 // total)
            print(
                f"\r  [{bar}] {completed}/{total}  "
                f"✓{results['success']} ✗{results['error']} ⊘{results['cancelled']}",
                end="",
                flush=True,
            )
            # Small jitter so not every request hits in the same millisecond
            await asyncio.sleep(random.uniform(0.05, 0.3))

    print(f"\n\nDone — {total} requests sent.")
    print(f"  success:   {results['success']}")
    print(f"  cancelled: {results['cancelled']}")
    print(f"  error:     {results['error']}")
    print("\nOpen http://localhost:3000 to see the dashboards.")


def main():
    parser = argparse.ArgumentParser(description="Seed the OlliveBird chatbot for demo data")
    parser.add_argument("--base-url", default="http://localhost:8080", help="Gateway URL")
    parser.add_argument("--requests", type=int, default=40, help="Number of requests to send")
    args = parser.parse_args()

    try:
        import httpx as _  # noqa: F401
    except ImportError:
        print("httpx not installed — run: pip install httpx")
        sys.exit(1)

    asyncio.run(run(args.base_url, args.requests))


if __name__ == "__main__":
    main()
