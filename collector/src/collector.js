// RUM collector core: pure helpers + a small state machine, no globals.
// Wired to the real browser in index.js; unit-tested in collector.test.js.

export const BEACON_VERSION = 1;

const PAGE_TYPES = ['cms-index-index', 'catalog-category-view', 'catalog-product-view'];

/** Magento page type from <body> classes; anything else is 'other'. */
export function pageType(body) {
  try {
    const cl = body && body.classList;
    if (cl) {
      for (let i = 0; i < PAGE_TYPES.length; i++) {
        if (cl.contains(PAGE_TYPES[i])) return PAGE_TYPES[i];
      }
    }
  } catch (e) {}
  return 'other';
}

/** Value of the Server-Timing entry named 'cache' (its description), or null. */
export function cacheStatus(navEntry) {
  try {
    const st = (navEntry && navEntry.serverTiming) || [];
    for (let i = 0; i < st.length; i++) {
      if (st[i].name === 'cache') return st[i].description || 'present';
    }
  } catch (e) {}
  return null;
}

const ms = (v) => (typeof v === 'number' && isFinite(v) ? Math.round(v) : undefined);
const str = (v, max = 200) => (typeof v === 'string' && v ? v.slice(0, max) : undefined);
// Resource and script URLs without query string or fragment (no personal data).
const url = (v) => {
  if (typeof v !== 'string' || !v) return undefined;
  return v.split(/[?#]/)[0].slice(0, 300);
};

/** Top LoAF scripts by duration: sourceURL, invoker, invokerType, duration. */
function loafScripts(loafs, limit = 3) {
  const scripts = [];
  (loafs || []).forEach((loaf) => {
    (loaf.scripts || []).forEach((s) => scripts.push(s));
  });
  scripts.sort((a, b) => (b.duration || 0) - (a.duration || 0));
  return scripts.slice(0, limit).map((s) => ({
    sourceURL: url(s.sourceURL),
    invoker: str(s.invoker),
    invokerType: str(s.invokerType, 40),
    duration: ms(s.duration),
  }));
}

/**
 * Trim web-vitals attribution to plain values: selectors, timings, resource URLs,
 * LoAF script sourceURL and invoker, durations. No DOM nodes, no PerformanceEntry objects.
 */
export function trimAttribution(metric) {
  const a = (metric && metric.attribution) || {};
  switch (metric && metric.name) {
    case 'LCP':
      return {
        target: str(a.target),
        url: url(a.url),
        timeToFirstByte: ms(a.timeToFirstByte),
        resourceLoadDelay: ms(a.resourceLoadDelay),
        resourceLoadDuration: ms(a.resourceLoadDuration),
        elementRenderDelay: ms(a.elementRenderDelay),
      };
    case 'INP': {
      const ls = a.longestScript;
      return {
        interactionTarget: str(a.interactionTarget),
        interactionType: str(a.interactionType, 20),
        inputDelay: ms(a.inputDelay),
        processingDuration: ms(a.processingDuration),
        presentationDelay: ms(a.presentationDelay),
        loadState: str(a.loadState, 30),
        totalScriptDuration: ms(a.totalScriptDuration),
        totalStyleAndLayoutDuration: ms(a.totalStyleAndLayoutDuration),
        totalPaintDuration: ms(a.totalPaintDuration),
        longestScript: ls && ls.entry
          ? {
              sourceURL: url(ls.entry.sourceURL),
              invoker: str(ls.entry.invoker),
              invokerType: str(ls.entry.invokerType, 40),
              subpart: str(ls.subpart, 30),
              duration: ms(ls.entry.duration),
              intersectingDuration: ms(ls.intersectingDuration),
            }
          : undefined,
        scripts: loafScripts(a.longAnimationFrameEntries),
      };
    }
    case 'CLS':
      return {
        largestShiftTarget: str(a.largestShiftTarget),
        largestShiftTime: ms(a.largestShiftTime),
        largestShiftValue: typeof a.largestShiftValue === 'number' ? Math.round(a.largestShiftValue * 1e4) / 1e4 : undefined,
        loadState: str(a.loadState, 30),
      };
    case 'FCP':
      return {
        timeToFirstByte: ms(a.timeToFirstByte),
        firstByteToFCP: ms(a.firstByteToFCP),
        loadState: str(a.loadState, 30),
      };
    case 'TTFB':
      return {
        waitingDuration: ms(a.waitingDuration),
        cacheDuration: ms(a.cacheDuration),
        dnsDuration: ms(a.dnsDuration),
        connectionDuration: ms(a.connectionDuration),
        requestDuration: ms(a.requestDuration),
      };
    default:
      return {};
  }
}

/** One metric as sent: CLS keeps 4 decimals, timings are whole-ish ms (2 decimals). */
export function toWire(metric) {
  const round = metric.name === 'CLS' ? 1e4 : 1e2;
  return {
    name: metric.name,
    id: metric.id,
    value: Math.round(metric.value * round) / round,
    delta: Math.round(metric.delta * round) / round,
    rating: metric.rating,
    navigationType: metric.navigationType,
    attribution: trimAttribution(metric),
  };
}

/**
 * Collector state machine. Metrics are buffered by id; on page hide the ones
 * changed since the last beacon are sent in one beacon (re-sends of an id are
 * deduped server-side, keeping the last value).
 *
 * deps: { vitals: {onLCP,...}, send(json) => bool, win, doc, sampleRate, random, context() }
 */
export function createCollector(deps) {
  const pending = new Map();
  const sampled = deps.random() < deps.sampleRate; // decided once per page view

  function record(metric) {
    try {
      pending.set(metric.id, toWire(metric));
    } catch (e) {}
  }

  function flush() {
    try {
      if (!pending.size) return false;
      const beacon = Object.assign({ v: BEACON_VERSION }, deps.context(), {
        metrics: Array.from(pending.values()),
      });
      pending.clear();
      return deps.send(JSON.stringify(beacon));
    } catch (e) {
      return false;
    }
  }

  function start() {
    if (!sampled) return false;
    try {
      const v = deps.vitals;
      [v.onLCP, v.onINP, v.onCLS, v.onFCP, v.onTTFB].forEach((on) => {
        try {
          on(record);
        } catch (e) {}
      });
      // Registered after web-vitals' own listeners, so final values are recorded first.
      deps.doc.addEventListener('visibilitychange', () => {
        try {
          if (deps.doc.visibilityState === 'hidden') flush();
        } catch (e) {}
      });
      // Fallback for pages that never became visible (opened in a background tab and
      // closed): there is no hidden transition, so flush on pagehide. Nothing is sent
      // twice, since flush() empties the buffer.
      deps.win.addEventListener('pagehide', () => {
        try {
          flush();
        } catch (e) {}
      });
    } catch (e) {}
    return true;
  }

  return { start, record, flush, sampled, pending };
}
