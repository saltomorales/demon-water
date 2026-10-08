-- Sanity queries. Run on the clickhouse app:
--   upsun ssh -A clickhouse -- '/app/bin/clickhouse client --user admin --password "$CH_ADMIN_PASSWORD" --multiquery' < clickhouse/queries/sanity.sql
-- Every query dedupes by metric id (last value wins), as the data rules require.

-- 1. CrUX-style p75 per metric, last 28 days, per tenant (all navigation types).
SELECT tenant, metric, count() AS page_views, round(quantileExactInclusive(0.75)(value), 3) AS p75
FROM
(
    SELECT tenant, metric, id, argMax(value, ts) AS value
    FROM rum.web_vitals
    WHERE ts >= now() - INTERVAL 28 DAY
    GROUP BY tenant, metric, id
)
GROUP BY tenant, metric
ORDER BY tenant, metric;

-- 2. Same, split by navigation type (bfcache/restore/prerender distort LCP and TTFB).
SELECT tenant, metric, navigation_type, count() AS page_views, round(quantileExactInclusive(0.75)(value), 3) AS p75
FROM
(
    SELECT tenant, metric, id, argMax(value, ts) AS value, argMax(navigation_type, ts) AS navigation_type
    FROM rum.web_vitals
    WHERE ts >= now() - INTERVAL 28 DAY
    GROUP BY tenant, metric, id
)
GROUP BY tenant, metric, navigation_type
ORDER BY tenant, metric, navigation_type;

-- 3. Duplicates waiting for a merge (re-sent ids); should shrink over time.
SELECT tenant, metric, count() - uniqExact(id) AS pending_duplicates
FROM rum.web_vitals
GROUP BY tenant, metric;

-- 4. Out-of-range values that slipped past Vector (must be empty).
SELECT metric, count() AS bad
FROM rum.web_vitals
WHERE (metric = 'CLS' AND (value < 0 OR value > 10))
   OR (metric != 'CLS' AND (value < 0 OR value > 60000))
GROUP BY metric;

-- 5. Daily aggregates vs raw for the last 2 days (page_views and p75 must match).
SELECT d.day, d.tenant, d.metric, d.page_views, r.page_views AS raw_page_views, d.p75, r.p75 AS raw_p75
FROM
(
    SELECT day, tenant, metric, sum(page_views) AS page_views, round(quantileMerge(0.75)(p75_state), 3) AS p75
    FROM rum.web_vitals_daily FINAL
    WHERE day >= today() - 1
    GROUP BY day, tenant, metric
) AS d
LEFT JOIN
(
    SELECT toDate(first_ts, 'UTC') AS day, tenant, metric, count() AS page_views, round(quantile(0.75)(value), 3) AS p75
    FROM
    (
        SELECT tenant, metric, id, argMax(value, ts) AS value, min(ts) AS first_ts
        FROM rum.web_vitals
        WHERE ts >= now() - INTERVAL 3 DAY
        GROUP BY tenant, metric, id
    )
    GROUP BY day, tenant, metric
) AS r USING (day, tenant, metric)
ORDER BY d.day, d.tenant, d.metric;
