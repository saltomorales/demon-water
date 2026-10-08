-- Daily aggregates for long-term trends (13 months; raw data lives 90 days).
-- An insert-time materialized view would count re-sent metric ids twice, so a
-- refreshable view recomputes the last 3 days hourly from deduped raw rows
-- (one value per metric id, the last one) and ReplacingMergeTree keeps the
-- newest computation per key. Query with FINAL and quantileMerge.
CREATE TABLE IF NOT EXISTS rum.web_vitals_daily
(
    day               Date,                                   -- UTC day of the page view (first sighting of the id)
    tenant            LowCardinality(String),
    metric            LowCardinality(String),
    page_type         LowCardinality(String),
    device            LowCardinality(String),
    navigation_type   LowCardinality(String),
    page_views        UInt64,                                 -- deduped values (one per metric id)
    good              UInt64,
    needs_improvement UInt64,
    poor              UInt64,
    p75_state         AggregateFunction(quantile(0.75), Float64),
    computed_at       DateTime
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY (tenant, metric, day, page_type, device, navigation_type)
TTL day + INTERVAL 13 MONTH;

CREATE MATERIALIZED VIEW IF NOT EXISTS rum.web_vitals_daily_refresh
REFRESH EVERY 1 HOUR APPEND TO rum.web_vitals_daily
AS
SELECT
    toDate(first_ts, 'UTC')              AS day,
    tenant,
    metric,
    page_type,
    device,
    navigation_type,
    count()                              AS page_views,
    countIf(rating = 'good')             AS good,
    countIf(rating = 'needs-improvement') AS needs_improvement,
    countIf(rating = 'poor')             AS poor,
    quantileState(0.75)(value)           AS p75_state,
    now()                                AS computed_at
FROM
(
    SELECT
        tenant,
        metric,
        id,
        argMax(value, ts)           AS value,
        argMax(rating, ts)          AS rating,
        argMax(page_type, ts)       AS page_type,
        argMax(device, ts)          AS device,
        argMax(navigation_type, ts) AS navigation_type,
        min(ts)                     AS first_ts
    FROM rum.web_vitals
    WHERE ts >= toStartOfDay(now(), 'UTC') - INTERVAL 3 DAY
    GROUP BY tenant, metric, id
)
WHERE first_ts >= toStartOfDay(now(), 'UTC') - INTERVAL 2 DAY
GROUP BY day, tenant, metric, page_type, device, navigation_type;
