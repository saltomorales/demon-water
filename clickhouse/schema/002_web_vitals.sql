-- Raw Web Vitals: one row per metric per page view, written by Vector.
-- Dedupe by metric id, keeping the last value (CLS/INP grow while the page lives
-- and the collector may re-send): ReplacingMergeTree versioned by receive time.
-- Merges are eventual, so queries must dedupe too (FINAL or argMax by id).
CREATE TABLE IF NOT EXISTS rum.web_vitals
(
    ts              DateTime64(3, 'UTC') CODEC(Delta, ZSTD),  -- receive time at Vector
    tenant          LowCardinality(String),
    metric          LowCardinality(String),                   -- LCP, INP, CLS, FCP, TTFB
    id              String,                                   -- web-vitals metric id
    value           Float64,                                  -- ms; CLS unitless
    delta           Float64,
    rating          LowCardinality(String),                   -- good, needs-improvement, poor
    navigation_type LowCardinality(String),
    page_type       LowCardinality(String),                   -- Magento body class or 'other'
    url_path        String,                                   -- no query string, no fragment
    cache_status    LowCardinality(String),                   -- Server-Timing 'cache', '' if absent
    release         LowCardinality(String),
    effective_type  LowCardinality(String),                   -- navigator.connection.effectiveType
    device          LowCardinality(String),                   -- desktop, mobile, tablet, other
    browser         LowCardinality(String),
    browser_major   LowCardinality(String),
    os              LowCardinality(String),
    attribution     String CODEC(ZSTD(3))                     -- trimmed attribution as JSON
)
ENGINE = ReplacingMergeTree(ts)
PARTITION BY toYYYYMM(ts)
ORDER BY (tenant, metric, id)
TTL toDateTime(ts) + INTERVAL 90 DAY;
