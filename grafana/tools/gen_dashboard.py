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
    argMax(navigation_type, ts) AS navigation_type, argMax(attribution, ts) AS attribution,
    min(ts) AS first_ts
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

# Row 5: attribution (what causes LCP, CLS and INP), 28 days.
# Attribution belongs to the last value of each metric id, i.e. the one that counts.
# Phase columns are p75 of each phase on its own: they do not add up to the metric's p75.
def attr_table(title, desc, sql, x, y, w, h, units):
    overrides = [{"matcher": {"id": "byName", "options": col},
                  "properties": [{"id": "unit", "value": unit}]} for col, unit in units.items()]
    add({"type": "table", "title": title, "description": desc,
         "targets": [target(sql, 1)],
         "fieldConfig": {"defaults": {}, "overrides": overrides},
         "options": {"showHeader": True, "cellHeight": "sm"}}, x, y, w, h)

J = "JSONExtractString(attribution, '{}')"
JF = "JSONExtractFloat(attribution, '{}')"
P75 = "round(quantileExactInclusive(0.75)({}))"
POOR = "round(countIf(rating = 'poor') / count() * 100, 1) AS poor_pct"

attr_table("LCP: elements (28 days)",
  "LCP element (CSS selector) per page view. Phases: time to first byte → resource load delay → resource load duration → element render delay.",
  f"""SELECT if({J.format('target')} = '', '(no element)', {J.format('target')}) AS element,
  topK(1)(page_type)[1] AS main_page_type, count() AS page_views, {P75.format('value')} AS lcp_p75, {POOR},
  {P75.format(JF.format('timeToFirstByte'))} AS ttfb_p75,
  {P75.format(JF.format('resourceLoadDelay'))} AS load_delay_p75,
  {P75.format(JF.format('resourceLoadDuration'))} AS load_duration_p75,
  {P75.format(JF.format('elementRenderDelay'))} AS render_delay_p75,
  topK(1)({J.format('url')})[1] AS top_resource
FROM {D28} AND metric = 'LCP'
GROUP BY element ORDER BY page_views * lcp_p75 DESC LIMIT 50""",
  0, 35, 24, 9,
  {"lcp_p75": "ms", "ttfb_p75": "ms", "load_delay_p75": "ms", "load_duration_p75": "ms", "render_delay_p75": "ms", "poor_pct": "percent"})

attr_table("CLS: shifting elements (28 days)",
  "Element with the largest single layout shift in the page view (web-vitals reports only the largest one).",
  f"""SELECT if({J.format('largestShiftTarget')} = '', '(no element)', {J.format('largestShiftTarget')}) AS element,
  topK(1)(page_type)[1] AS main_page_type, count() AS page_views,
  round(quantileExactInclusive(0.75)(value), 3) AS cls_p75, {POOR},
  round(quantileExactInclusive(0.75)({JF.format('largestShiftValue')}), 3) AS largest_shift_p75,
  round(quantileExactInclusive(0.5)({JF.format('largestShiftTime')})) AS shift_time_median,
  topK(1)({J.format('loadState')})[1] AS load_state
FROM {D28} AND metric = 'CLS' AND value > 0
GROUP BY element ORDER BY page_views * cls_p75 DESC LIMIT 50""",
  0, 44, 24, 9,
  {"shift_time_median": "ms", "poor_pct": "percent"})

attr_table("INP: elements (28 days)",
  "Interaction target per page view. Phases: input delay (main thread busy) → processing (event handlers) → presentation delay (style, layout, paint).",
  f"""SELECT if({J.format('interactionTarget')} = '', '(no element)', {J.format('interactionTarget')}) AS element,
  topK(1)({J.format('interactionType')})[1] AS type,
  topK(1)(page_type)[1] AS main_page_type, count() AS page_views, {P75.format('value')} AS inp_p75, {POOR},
  {P75.format(JF.format('inputDelay'))} AS input_delay_p75,
  {P75.format(JF.format('processingDuration'))} AS processing_p75,
  {P75.format(JF.format('presentationDelay'))} AS presentation_p75,
  topK(1)({J.format('loadState')})[1] AS load_state
FROM {D28} AND metric = 'INP'
GROUP BY element ORDER BY page_views * inp_p75 DESC LIMIT 50""",
  0, 53, 24, 9,
  {"inp_p75": "ms", "input_delay_p75": "ms", "processing_p75": "ms", "presentation_p75": "ms", "poor_pct": "percent"})

attr_table("INP: longest scripts (28 days)",
  "Longest script (Long Animation Frames) during the INP interaction: source file without query string and its invoker, e.g. BUTTON#id.onclick.",
  f"""SELECT if(JSONExtractString(attribution, 'longestScript', 'sourceURL') = '', '(unknown or inline)', JSONExtractString(attribution, 'longestScript', 'sourceURL')) AS script,
  JSONExtractString(attribution, 'longestScript', 'invoker') AS invoker,
  topK(1)(JSONExtractString(attribution, 'longestScript', 'subpart'))[1] AS phase,
  count() AS page_views, {P75.format('value')} AS inp_p75,
  {P75.format("JSONExtractFloat(attribution, 'longestScript', 'duration')")} AS script_duration_p75
FROM {D28} AND metric = 'INP' AND JSONHas(attribution, 'longestScript')
GROUP BY script, invoker ORDER BY page_views * script_duration_p75 DESC LIMIT 50""",
  0, 62, 24, 9,
  {"inp_p75": "ms", "script_duration_p75": "ms"})

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
