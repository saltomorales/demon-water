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
- Sampling: decided once per page view; the rate is a config constant (`RUM_SAMPLE_RATE` in `collector/build.mjs`, 1 = 100% during the POC so we can compare with RUM Vision).
- Beacon on `visibilitychange` → `hidden`, plus a `pagehide` fallback for pages that never became visible (background tab closed unseen). Only metrics changed since the last beacon are sent; nothing is sent twice.
- `web-vitals@6.2.2` (pinned). Build: `cd collector && npm ci && npm run build` → `vector/public/rum.js` (committed; ~7.4 KB gzip, the build fails over 10 KB). Tests: `cd collector && npx vitest run`.
- Served from the ingest domain: `/static/rum.js`. GTM Custom HTML tag: `<script async src="https://ingest.<domain>/static/rum.js"></script>`. Ingest URL is a build constant (`RUM_ENDPOINT`).
- E2E test page: `https://ingest.<domain>/static/e2e/` (Magento product body class, late banner → CLS, slow button → INP, `Server-Timing: cache;desc=HIT`). Its origin is allowlisted as tenant `e2e`.
- A tab that is hidden from load (e.g. an automation window in the background) only yields TTFB: web-vitals skips FCP/LCP/INP there by design. Run the browser e2e with the window visible to see all five metrics.
- Budget: under 10 KB gzipped. Load async. Never throw: wrap everything in try/catch.

## Ingest rules (Vector)

- `http_server` source. Parse the body as JSON regardless of `Content-Type`.
- Tenant: from the page origin, checked against an allowlist. Reject unknown origins.
- Reject impossible values: CLS < 0 or > 10, LCP, INP or TTFB < 0 or > 60000 ms.
- Enrich: device and browser from the User-Agent. Then drop the IP and the raw User-Agent.
- Explode one beacon into one row per metric.
- Write to ClickHouse in batches. No per-event inserts.
- Every transform has a `vector test` case: valid beacons and garbage.
- Beacon contract v1 (collector → Vector): `{"v":1,"url","pageType","cache","release","ect","metrics":[{"name","id","value","delta","rating","navigationType","attribution"}]}`. Max 64 KB, max 20 metrics.
- Tenant allowlist: `vector/tenants.csv` (`origin,tenant`), matched against the `Origin` header, or the origin part of `Referer` when Origin is missing (Chrome omits it on same-origin beacons). The page `url` must have the same origin. Referer is never stored or logged. `https://rum-e2e.invalid` → `e2e` is the synthetic test tenant.
- Beacon-level errors drop the whole beacon (logged as `{"rejected": reason, "origin"}` only, throttled). Metric-level errors drop just that metric. FCP uses the same 0..60000 ms bound as the other timings.
- Device from `parse_user_agent` (reliable mode): `desktop`, `mobile`, `tablet`, `other`. Android tablets often come out as `mobile`.
- Run tests: `./vector/test.sh` (uses `vector/tests/tenants.csv`). Local and server Vector must be the same version (`vector/install.sh`).

## Data rules

- Units: milliseconds for all timings; CLS is unitless.
- Dedupe by metric `id` (keep the last value): `rum.web_vitals` is `ReplacingMergeTree(ts)` ordered by `(tenant, metric, id)`. Merges are eventual, so every query must dedupe itself (`FINAL` or `argMax(value, ts)` by id).
- Percentiles: p75 over per-page-view values, 28-day window (CrUX-compatible).
    - Method: `quantileExactInclusive(0.75)` (linear interpolation, like numpy/Excel PERCENTILE.INC). Not `quantileExact`: it picks index floor(0.75n) and runs high on small samples. Daily aggregates use `quantileState(0.75)`/`quantileMerge`, which matches it exactly up to 8192 values per state and is approximate above.
    - "Per page view" = one value per web-vitals metric id (its last value). A bfcache restore gets a new id, so it counts as its own page view (as in CrUX).
    - Day of a page view = UTC day of the first sighting of its id.
    - Verified on Upsun: LCP 1000/2000/3000/4000 with 4000 re-sent as 5000 → p75 3500 in raw queries and in daily aggregates, 4 page views.
- Daily aggregates: `rum.web_vitals_daily` (ReplacingMergeTree by `computed_at`), filled by the refreshable view `rum.web_vitals_daily_refresh` (every hour, last 3 days, from deduped raw). Not an insert-time MV: that would count re-sent ids twice. Query with `FINAL`.
- Grafana dashboard: generated by `grafana/tools/gen_dashboard.py` → `grafana/dashboards/rum-overview.json` (edit the generator, not the JSON). Stat panels use a fixed 28-day window; trends follow the time picker; variables: tenant, page type, device, navigation type.
    - Attribution section (28 days): LCP elements (+ resource URL, 4 phases), CLS shifting elements (largest shift only, as web-vitals reports it), INP elements (3 phases) and INP longest scripts (sourceURL + invoker). Phase columns are p75 of each phase on its own and do not add up to the metric's p75. FCP and TTFB have no element; their timing breakdown is stored but not on the dashboard.
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
    - Vector binary: official static build pinned in `vector/install.sh` (Nix only has 0.55), same version as local.
- Collector runs cross-origin (shop → Upsun domain). The shop CSP `connect-src` may need our domain.
- No changes to the Magento codebase during the POC.

## Definition of done (every task)

- Tests pass (`vector test`, collector unit tests).
- Verified end to end: a beacon from a test page via Chrome DevTools MCP lands in ClickHouse and shows in Grafana.
- Metric math reviewed against the data rules above.
- `CLAUDE.md` updated if a decision changed.
## Open items

- **Shop allowlist (placeholder):** `vector/tenants.csv` has only the synthetic `e2e` tenant. Before the first real shop: add one line per origin (`https://www.shop.tld,shop`, exact scheme + host, one line per variant such as with/without `www`), push, and add the Upsun ingest domain to the shop CSP `connect-src`.
- **Plan upgrade:** Development → Medium High Memory before real shop traffic; the team lead has to confirm the POC offer covers it.
