# RUM POC

Self-hosted Real User Monitoring for Magento 2 shops. Goal: replace RUM Vision with our own stack, validated against it.

## Architecture

```
Browser (web-vitals/attribution + wrapper, injected via GTM)
  → sendBeacon (text/plain) → Vector (Upsun app)
  → ClickHouse (Upsun app, self-managed) → Grafana (Upsun app)
```

Reference docs: `docs/open-source-rum-stack.md`, `docs/porownanie-rum.md`.

## Repo layout

```
collector/   browser wrapper, built to a single IIFE for a GTM Custom HTML tag
vector/      vector.yaml + unit tests (vector test)
clickhouse/  server config, users, schema (applied on start), sanity queries
grafana/     provisioning: datasource + dashboards (JSON)
local/       docker-compose for local dev
.platform/   applications.yaml, routes.yaml, services.yaml (Upsun Fixed format)
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

- ClickHouse is never exposed publicly (no route); Vector and Grafana reach it via app-to-app relationships.
- ClickHouse users: `vector` (INSERT/SELECT on `rum`), `grafana` (SELECT, readonly profile), `admin` (migrations). Passwords: Upsun sensitive variables `env:CH_*_PASSWORD`.
- Secrets go in Upsun variables only, never in the repo.
- Grafana: anonymous access off.

## Constraints

- Upsun **Fixed** (our org is Fixed; Flex is not an option). Fixed has no ClickHouse service, so ClickHouse runs as a composable app (Nix `clickhouse`) with a local disk. We own its upgrades, memory tuning and backups. No HA, fine for the POC.
    - All three apps use `composable:26.05` with Nix packages; each app has its own source root (`vector/`, `clickhouse/`, `grafana/`).
    - Project `xeu4pm5hpww7u`, org creativestyle, region `eu-5.platform.sh` (Sweden, EU, low-carbon discount). Git remote `upsun`.
    - Plan: Development (free under the company's Upsun POC offer, to be confirmed) while building; Medium High Memory before real shop traffic. Disk is shared across apps: keep the sum of `disk` within the plan.
    - Routes: `https://{default}/` → Grafana, `https://ingest.{default}/rum` → Vector.
    - Relationship credentials are read from `$PLATFORM_RELATIONSHIPS` (base64 JSON, parsed with `jq`) in each app's `start.sh`.
    - Schema: `clickhouse/schema/*.sql`, applied in order by `migrate.sh` on every start (`post_start`), so every statement must be idempotent.
    - Vector ≥ 0.59 disables env-var interpolation by default; we start it with `--dangerously-allow-env-var-interpolation` (config is ours, needed for `$PORT` and ClickHouse credentials).
    - `upsun app:config-validate` only understands the Flex format; the real validation happens on `git push upsun`.
    - ClickHouse binary: official static LTS build, pinned and sha512-checked in `clickhouse/install.sh` (the Nix package crashes on start: "Cannot allocate ThreadStack"). Upgrade by bumping `CH_VERSION`.
    - Containers expose no cgroup memory info: ClickHouse sees the host RAM, so memory caps in `config.xml`/`users.xml` must be absolute values.
    - Development plan: each app nominally gets 128 MB RAM / 0.4 CPU (`/run/config.json`), not enforced strictly but not production-grade.
    - Vector on Upsun comes from Nix (0.55 on `composable:26.05`); keep the local `vector` version in mind when running `vector test`.
- Collector runs cross-origin (shop → Upsun domain). The shop CSP `connect-src` may need our domain.
- No changes to the Magento codebase during the POC.

## Definition of done (every task)

- Tests pass (`vector test`, collector unit tests).
- Verified end to end: a beacon from a test page via Chrome DevTools MCP lands in ClickHouse and shows in Grafana.
- Metric math reviewed against the data rules above.
- `CLAUDE.md` updated if a decision changed.