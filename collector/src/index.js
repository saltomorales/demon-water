// Browser entry: wires the collector core to web-vitals (attribution build) and sendBeacon.
// Built to a single IIFE (build.mjs); loaded async via GTM.
import { onLCP, onINP, onCLS, onFCP, onTTFB } from 'web-vitals/attribution';
import { createCollector, pageType, cacheStatus } from './collector.js';

// Build-time constants (build.mjs `define`).
/* global __RUM_ENDPOINT__, __RUM_SAMPLE_RATE__ */
const ENDPOINT = __RUM_ENDPOINT__;
const SAMPLE_RATE = __RUM_SAMPLE_RATE__;

try {
  const win = window;
  const doc = document;
  if (!win.__rumCollector && win.navigator && typeof win.navigator.sendBeacon === 'function') {
    const context = () => {
      let nav;
      try {
        nav = performance.getEntriesByType('navigation')[0];
      } catch (e) {}
      const conn = win.navigator.connection;
      return {
        // Origin + path only: no query string, no fragment.
        url: win.location.origin + win.location.pathname,
        pageType: pageType(doc.body),
        cache: cacheStatus(nav),
        release: typeof win.RUM_RELEASE === 'string' ? win.RUM_RELEASE : null,
        ect: (conn && conn.effectiveType) || null,
      };
    };
    const send = (json) => {
      try {
        // text/plain keeps it a CORS-simple request (no preflight).
        return win.navigator.sendBeacon(ENDPOINT, new Blob([json], { type: 'text/plain' }));
      } catch (e) {
        return false;
      }
    };
    const collector = createCollector({
      vitals: { onLCP, onINP, onCLS, onFCP, onTTFB },
      send,
      win,
      doc,
      sampleRate: SAMPLE_RATE,
      random: Math.random,
      context,
    });
    win.__rumCollector = collector;
    collector.start();
  }
} catch (e) {}
