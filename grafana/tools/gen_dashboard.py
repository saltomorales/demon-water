# Generates grafana/dashboards/rum-overview.json: python3 grafana/tools/gen_dashboard.py grafana/dashboards/rum-overview.json
import json, sys
DS = {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"}
FILTERS = ("page_type IN (${page_type:singlequote}) AND device IN (${device:singlequote}) "
           "AND navigation_type IN (${navigation_type:singlequote})")

def dedup(where):
    # One row per metric id with its last value (data rule: dedupe by id, keep last).
    return f"""(
  SELECT tenant, metric, id,
    argMax(value, ts) AS value, argMax(rating, ts) AS rating,
    argMax(page_type, ts) AS page_type, argMax(device, ts) AS device,
    argMax(navigation_type, ts) AS navigation_type, min(ts) AS first_ts
  FROM rum.web_vitals
  WHERE tenant IN (${{tenant:singlequote}}) AND {where}
  GROUP BY tenant, metric, id
)
WHERE {FILTERS}"""

D28 = dedup("ts >= now() - INTERVAL 28 DAY")
DRANGE = dedup("$__timeFilter(ts)")

THRESH = {"LCP": (2500, 4000), "INP": (200, 500), "CLS": (0.1, 0.25), "FCP": (1800, 3000), "TTFB": (800, 1800)}
def steps(m):
    g, p = THRESH[m]
    return {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "orange", "value": g}, {"color": "red", "value": p}]}

def target(sql, fmt):
    return {"refId": "A", "datasource": DS, "editorType": "sql", "format": fmt,
            "queryType": "timeseries" if fmt == 0 else "table", "rawSql": sql}

panels = []
pid = 1
def add(p, x, y, w, h):
    global pid
    p.update({"id": pid, "datasource": DS, "gridPos": {"x": x, "y": y, "w": w, "h": h}})
    panels.append(p); pid += 1

# Row 1: CrUX-style p75 stats, 28 days.
for i, m in enumerate(["LCP", "INP", "CLS", "FCP", "TTFB"]):
    unit = "none" if m == "CLS" else "ms"
    dec = 2 if m == "CLS" else 0
    add({"type": "stat", "title": f"{m} p75 (28 days)",
         "description": "p75 (linear interpolation, quantileExactInclusive) over per-page-view values deduped by metric id, fixed 28-day window like CrUX. Thresholds: Core Web Vitals good / poor.",
         "targets": [target(f"SELECT quantileExactInclusive(0.75)(value) AS p75, count() AS page_views FROM {D28} AND metric = '{m}'", 1)],
         "fieldConfig": {"defaults": {"unit": unit, "decimals": dec, "thresholds": steps(m), "color": {"mode": "thresholds"}},
                         "overrides": [{"matcher": {"id": "byName", "options": "page_views"},
                                        "properties": [{"id": "unit", "value": "short"}, {"id": "decimals", "value": 0},
                                                       {"id": "color", "value": {"mode": "fixed", "fixedColor": "text"}},
                                                       {"id": "displayName", "value": "page views"}]}]},
         "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                     "colorMode": "background", "graphMode": "none", "textMode": "value_and_name", "orientation": "vertical"}},
        i * 5 if i < 4 else 20, 0, 5 if i < 4 else 4, 5)

# Row 2: daily p75 trends (raw, deduped) for the selected range.
add({"type": "timeseries", "title": "Daily p75: LCP, INP, FCP, TTFB (ms)",
     "description": "Per day of first sighting of the page view, deduped by metric id. Raw data is kept 90 days.",
     "targets": [target(f"SELECT toStartOfDay(first_ts) AS time, metric, quantileExactInclusive(0.75)(value) AS p75 FROM {DRANGE} AND metric != 'CLS' GROUP BY time, metric ORDER BY time", 0)],
     "fieldConfig": {"defaults": {"unit": "ms", "custom": {"drawStyle": "line", "pointSize": 6, "showPoints": "always"}}, "overrides": []},
     "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}}, 0, 5, 16, 8)
add({"type": "timeseries", "title": "Daily p75: CLS",
     "targets": [target(f"SELECT toStartOfDay(first_ts) AS time, metric, quantileExactInclusive(0.75)(value) AS p75 FROM {DRANGE} AND metric = 'CLS' GROUP BY time, metric ORDER BY time", 0)],
     "fieldConfig": {"defaults": {"unit": "none", "decimals": 3, "custom": {"drawStyle": "line", "pointSize": 6, "showPoints": "always"}}, "overrides": []},
     "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}}, 16, 5, 8, 8)

# Row 3: rating distribution and segments, 28 days.
add({"type": "table", "title": "Rating distribution (28 days)",
     "targets": [target(f"SELECT metric, count() AS page_views, round(countIf(rating = 'good') / count() * 100, 1) AS good_pct, round(countIf(rating = 'needs-improvement') / count() * 100, 1) AS needs_improvement_pct, round(countIf(rating = 'poor') / count() * 100, 1) AS poor_pct FROM {D28} GROUP BY metric ORDER BY metric", 1)],
     "fieldConfig": {"defaults": {}, "overrides": []}, "options": {"showHeader": True}}, 0, 13, 12, 7)
add({"type": "table", "title": "p75 by page type (28 days)",
     "targets": [target(f"SELECT page_type, metric, count() AS page_views, round(quantileExactInclusive(0.75)(value), 3) AS p75 FROM {D28} GROUP BY page_type, metric ORDER BY page_type, metric", 1)],
     "fieldConfig": {"defaults": {}, "overrides": []}, "options": {"showHeader": True}}, 12, 13, 12, 7)
add({"type": "table", "title": "p75 by navigation type (28 days)",
     "description": "back-forward-cache, restore and prerender distort LCP and TTFB; filter them with the navigation_type variable.",
     "targets": [target(f"SELECT navigation_type, metric, count() AS page_views, round(quantileExactInclusive(0.75)(value), 3) AS p75 FROM {D28} GROUP BY navigation_type, metric ORDER BY navigation_type, metric", 1)],
     "fieldConfig": {"defaults": {}, "overrides": []}, "options": {"showHeader": True}}, 0, 20, 12, 7)
add({"type": "table", "title": "p75 by device (28 days)",
     "targets": [target(f"SELECT device, metric, count() AS page_views, round(quantileExactInclusive(0.75)(value), 3) AS p75 FROM {D28} GROUP BY device, metric ORDER BY device, metric", 1)],
     "fieldConfig": {"defaults": {}, "overrides": []}, "options": {"showHeader": True}}, 12, 20, 12, 7)

# Row 4: long-term trend from daily aggregates (13 months).
add({"type": "timeseries", "title": "Daily p75 from aggregates (13 months)",
     "description": "rum.web_vitals_daily (refreshed hourly, deduped); quantileMerge over the selected segments.",
     "targets": [target("SELECT toDateTime(day) AS time, metric, quantileMerge(0.75)(p75_state) AS p75 FROM rum.web_vitals_daily FINAL "
                        "WHERE tenant IN (${tenant:singlequote}) AND " + FILTERS + " AND metric != 'CLS' AND $__timeFilter(toDateTime(day)) "
                        "GROUP BY time, metric ORDER BY time", 0)],
     "fieldConfig": {"defaults": {"unit": "ms", "custom": {"drawStyle": "line", "pointSize": 6, "showPoints": "always"}}, "overrides": []},
     "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}}, 0, 27, 24, 8)

def var(name, label, col):
    return {"name": name, "label": label, "type": "query", "datasource": DS,
            "query": {"rawSql": f"SELECT DISTINCT {col} FROM rum.web_vitals WHERE ts >= now() - INTERVAL 90 DAY ORDER BY {col}", "editorType": "sql", "format": 1},
            "definition": f"SELECT DISTINCT {col} FROM rum.web_vitals", "refresh": 2, "multi": True, "includeAll": True,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]}, "sort": 1}

dash = {
    "uid": "rum-overview", "title": "RUM overview", "tags": ["rum"], "timezone": "utc", "schemaVersion": 39,
    "editable": False, "refresh": "5m", "time": {"from": "now-28d", "to": "now"},
    "templating": {"list": [var("tenant", "Tenant", "tenant"), var("page_type", "Page type", "page_type"),
                            var("device", "Device", "device"), var("navigation_type", "Navigation type", "navigation_type")]},
    "panels": panels,
}
json.dump(dash, open(sys.argv[1], "w"), indent=2)
print(len(panels), "panels")
