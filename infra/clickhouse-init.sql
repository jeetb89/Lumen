CREATE TABLE IF NOT EXISTS inference_logs (
    event_id            UUID,
    schema_version      UInt16,
    event_timestamp     DateTime64(3, 'UTC'),

    conversation_id     UUID,
    message_id          Nullable(UUID),
    user_id             LowCardinality(String),

    provider            LowCardinality(String),
    model               LowCardinality(String),

    input_preview       String,
    input_chars         UInt32,
    num_messages        UInt16,
    params              String,                         -- JSON-as-string

    output_preview      String,
    output_chars        UInt32,
    finish_reason       LowCardinality(Nullable(String)),

    prompt_tokens       Nullable(UInt32),
    completion_tokens   Nullable(UInt32),
    total_tokens        Nullable(UInt32),

    started_at          DateTime64(3, 'UTC'),
    ended_at            DateTime64(3, 'UTC'),
    latency_ms          UInt32,
    ttft_ms             Nullable(UInt32),

    status              LowCardinality(String),         -- success|error|cancelled|timeout
    error               Nullable(String),

    -- Derived columns computed at ingest time
    cost_usd            Nullable(Decimal(10, 6)),
    tokens_per_second   Nullable(Float32),

    -- Bookkeeping
    ingested_at         DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_timestamp)
ORDER BY (event_timestamp, provider, model, conversation_id)
TTL toDateTime(event_timestamp) + INTERVAL 90 DAY;


-- Per-minute rollup for dashboard queries
CREATE TABLE IF NOT EXISTS inference_minutely (
    minute       DateTime,
    provider     LowCardinality(String),
    model        LowCardinality(String),
    status       LowCardinality(String),
    requests     UInt64,
    p50_latency  AggregateFunction(quantile(0.5), UInt32),
    p95_latency  AggregateFunction(quantile(0.95), UInt32),
    p99_latency  AggregateFunction(quantile(0.99), UInt32),
    sum_tokens   UInt64,
    sum_cost     Decimal(14, 6)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(minute)
ORDER BY (minute, provider, model, status);

CREATE MATERIALIZED VIEW IF NOT EXISTS inference_minutely_mv
TO inference_minutely AS
SELECT
    toStartOfMinute(event_timestamp)                       AS minute,
    provider, model, status,
    count()                                                AS requests,
    quantileState(0.5)(latency_ms)                         AS p50_latency,
    quantileState(0.95)(latency_ms)                        AS p95_latency,
    quantileState(0.99)(latency_ms)                        AS p99_latency,
    sum(coalesce(total_tokens, 0))                         AS sum_tokens,
    sum(coalesce(cost_usd, toDecimal64(0, 6)))             AS sum_cost
FROM inference_logs
GROUP BY minute, provider, model, status;
