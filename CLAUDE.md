# RUM POC

Self-hosted Real User Monitoring for Magento 2 shops. Goal: replace RUM Vision with our own stack, validated against it.

## Architecture

```
Browser (web-vitals/attribution + wrapper, injected via GTM)
  → sendBeacon (text/plain) → Vector (Upsun app)
  → ClickHouse (Upsun service) → Grafana (Upsun app)
```

Reference docs: `docs/open-source-rum-stack.md`, `docs/porownanie-rum.md`.

## Repo layout

```
collector/   browser wrapper, built to a single IIFE for a GTM Custom HTML tag
vector/      vector.yaml + unit tests (vector test)
clickhouse/  schema, materialized views, sanity queries
grafana/     provisioning: datasource + dashboards (JSON)
local/       docker-compose for local dev
.upsun/      config.yaml
docs/        reference docs
```

## Collector rules

- `web-vitals` with the `attribution` build only. No other RUM libs.
- Metrics: LCP, INP, CLS, FCP, TTFB.
- One beacon per page view on `visibilitychange` → `hidden`. Re-send after bfcache restore is fine; the server dedupes.
- Send `navigator.sendBeacon(url, new Blob([json], { type: 'text/plain' }))`. Never `application/json` (it triggers a CORS preflight).
- Every metric carries `id`, `value`, `delta`, `rating`, `navigationType`.
- Context:
    - page type from `<body>` classes: `cms-index-index`, `catalog-category-view`, `catalog-product-view`, otherwise `other`
    - cache status from the `Server-Timing` entry `cache`
    - release from `window.RUM_RELEASE` if present
    - `navigator.connection.effectiveType`
- Trim attribution to plain values: selectors, timings, resource URLs, LoAF script `sourceURL` and `invoker`, plus durations. No DOM nodes, no full `PerformanceEntry` objects.
- Sampling: decided once per page view; the rate is a config constant.
- Budget: under 10 KB gzipped. Load async. Never throw: wrap everything in try/catch.

## Ingest rules (Vector)

- `http_server` source. Parse the body as JSON regardless of `Content-Type`.
- Tenant: from the page origin, checked against an allowlist. Reject unknown origins.
- Reject impossible values: CLS < 0 or > 10, LCP, INP or TTFB < 0 or > 60000 ms.
- Enrich: device and browser from the User-Agent. Then drop the IP and the raw User-Agent.
- Explode one beacon into one row per metric.
- Write to ClickHouse in batches. No per-event inserts.
- Every transform has a `vector test` case: valid beacons and garbage.

## Data rules

- Units: milliseconds for all timings; CLS is unitless.
- Dedupe by metric `id` (keep the last value).
- Percentiles: p75 over per-page-view values, 28-day window (CrUX-compatible).
- Always allow segmenting by `navigationType`. `back-forward-cache`, `restore` and `prerender` distort LCP and TTFB.
- Raw table: TTL 90 days. Daily aggregates (`quantileState` / `quantileMerge`): 13 months.
- Multi-tenant from day one: a `tenant` column in every table.

## Privacy

- No cookies, no IP storage, no user or session IDs, no query strings with personal data (strip URL params).
- No session replay.

## Security

- ClickHouse is never exposed publicly; Grafana reads it via an Upsun relationship.
- Secrets go in Upsun variables only, never in the repo.
- Grafana: anonymous access off.

## Constraints

- Upsun: composable image with Nix packages for Vector and Grafana; ClickHouse as a managed service (no HA, fine for the POC).
    - Project `xeu4pm5hpww7u`, org creativestyle, region `eu-5.platform.sh` (Sweden, EU, low-carbon discount). Git remote `upsun`.
    - Routes: `https://{default}/` → Grafana, `https://ingest.{default}/rum` → Vector.
    - ClickHouse endpoints: `ingest` (rw, Vector), `dashboards` (ro, Grafana), `admin` (migrations via `upsun tunnel`).
    - Vector ≥ 0.59 disables env-var interpolation by default; we start it with `--dangerously-allow-env-var-interpolation` (config is ours, needed for `$PORT` and relationship vars).
- Collector runs cross-origin (shop → Upsun domain). The shop CSP `connect-src` may need our domain.
- No changes to the Magento codebase during the POC.

## Definition of done (every task)

- Tests pass (`vector test`, collector unit tests).
- Verified end to end: a beacon from a test page via Chrome DevTools MCP lands in ClickHouse and shows in Grafana.
- Metric math reviewed against the data rules above.
- `CLAUDE.md` updated if a decision changed.