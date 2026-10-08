// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { pageType, cacheStatus, trimAttribution, toWire, createCollector } from './collector.js';

const body = (cls) => {
  const b = document.createElement('body');
  if (cls) b.className = cls;
  return b;
};

describe('pageType', () => {
  it('detects Magento page types from body classes', () => {
    expect(pageType(body('page-layout-1column cms-index-index'))).toBe('cms-index-index');
    expect(pageType(body('catalog-category-view page-products'))).toBe('catalog-category-view');
    expect(pageType(body('catalog-product-view product-shoe'))).toBe('catalog-product-view');
  });
  it('falls back to other', () => {
    expect(pageType(body('checkout-index-index'))).toBe('other');
    expect(pageType(null)).toBe('other');
    expect(pageType({})).toBe('other');
  });
});

describe('cacheStatus', () => {
  it('reads the Server-Timing entry named cache', () => {
    expect(cacheStatus({ serverTiming: [{ name: 'db', description: '' }, { name: 'cache', description: 'HIT' }] })).toBe('HIT');
    expect(cacheStatus({ serverTiming: [{ name: 'cache', description: '' }] })).toBe('present');
  });
  it('returns null when absent or broken', () => {
    expect(cacheStatus({ serverTiming: [] })).toBe(null);
    expect(cacheStatus(undefined)).toBe(null);
  });
});

describe('trimAttribution', () => {
  it('keeps plain LCP values, drops DOM nodes, entries and query strings', () => {
    const a = trimAttribution({
      name: 'LCP',
      attribution: {
        target: 'img.hero',
        url: 'https://cdn.example/hero.jpg?token=secret#x',
        timeToFirstByte: 300.4,
        resourceLoadDelay: 10.6,
        resourceLoadDuration: 200,
        elementRenderDelay: 5,
        lcpEntry: { element: document.createElement('img') },
        navigationEntry: { name: 'x' },
        lcpResourceEntry: {},
      },
    });
    expect(a).toEqual({
      target: 'img.hero',
      url: 'https://cdn.example/hero.jpg',
      timeToFirstByte: 300,
      resourceLoadDelay: 11,
      resourceLoadDuration: 200,
      elementRenderDelay: 5,
    });
  });

  it('keeps INP LoAF script sourceURL, invoker and durations, top 3 by duration', () => {
    const script = (d, n) => ({ duration: d, sourceURL: `https://shop.example/${n}.js?v=1`, invoker: `${n}.onclick`, invokerType: 'event-listener', window: {} });
    const a = trimAttribution({
      name: 'INP',
      attribution: {
        interactionTarget: 'button.add-to-cart',
        interactionType: 'pointer',
        inputDelay: 12.2,
        processingDuration: 150.7,
        presentationDelay: 30,
        loadState: 'complete',
        processedEventEntries: [{}],
        longAnimationFrameEntries: [{ scripts: [script(10, 'a'), script(90, 'b')] }, { scripts: [script(50, 'c'), script(70, 'd')] }],
        longestScript: { entry: script(90, 'b'), subpart: 'processing-duration', intersectingDuration: 88.8 },
      },
    });
    expect(a.interactionTarget).toBe('button.add-to-cart');
    expect(a.processingDuration).toBe(151);
    expect(a.longestScript).toEqual({
      sourceURL: 'https://shop.example/b.js',
      invoker: 'b.onclick',
      invokerType: 'event-listener',
      subpart: 'processing-duration',
      duration: 90,
      intersectingDuration: 89,
    });
    expect(a.scripts.map((s) => s.duration)).toEqual([90, 70, 50]);
    expect(JSON.stringify(a)).not.toContain('window');
    expect(a).not.toHaveProperty('processedEventEntries');
    expect(a).not.toHaveProperty('longAnimationFrameEntries');
  });

  it('trims CLS, FCP and TTFB', () => {
    expect(trimAttribution({ name: 'CLS', attribution: { largestShiftTarget: 'div.banner', largestShiftValue: 0.123456, largestShiftTime: 1500.2, largestShiftEntry: {}, largestShiftSource: { node: {} }, loadState: 'dom-interactive' } }))
      .toEqual({ largestShiftTarget: 'div.banner', largestShiftValue: 0.1235, largestShiftTime: 1500, loadState: 'dom-interactive' });
    expect(trimAttribution({ name: 'FCP', attribution: { timeToFirstByte: 100, firstByteToFCP: 400, loadState: 'loading', fcpEntry: {} } }))
      .toEqual({ timeToFirstByte: 100, firstByteToFCP: 400, loadState: 'loading' });
    expect(trimAttribution({ name: 'TTFB', attribution: { waitingDuration: 1, cacheDuration: 2, dnsDuration: 3, connectionDuration: 4, requestDuration: 5, navigationEntry: {} } }))
      .toEqual({ waitingDuration: 1, cacheDuration: 2, dnsDuration: 3, connectionDuration: 4, requestDuration: 5 });
  });

  it('never throws on missing attribution', () => {
    expect(trimAttribution({ name: 'LCP' }).target).toBeUndefined();
    expect(trimAttribution(undefined)).toEqual({});
  });
});

describe('toWire', () => {
  it('carries id, value, delta, rating, navigationType', () => {
    const w = toWire({ name: 'CLS', id: 'v6-1', value: 0.123456, delta: 0.0234567, rating: 'needs-improvement', navigationType: 'navigate', attribution: {} });
    expect(w).toMatchObject({ name: 'CLS', id: 'v6-1', value: 0.1235, delta: 0.0235, rating: 'needs-improvement', navigationType: 'navigate' });
    expect(toWire({ name: 'LCP', id: 'x', value: 1234.5678, delta: 1234.5678, rating: 'good', navigationType: 'reload' }).value).toBe(1234.57);
  });
});

function setup({ random = 0, sampleRate = 1 } = {}) {
  const handlers = {};
  const vitals = {};
  for (const n of ['LCP', 'INP', 'CLS', 'FCP', 'TTFB']) vitals['on' + n] = vi.fn((cb) => (handlers[n] = cb));
  const send = vi.fn(() => true);
  let visibility = 'visible';
  const listeners = [];
  const doc = {
    get visibilityState() {
      return visibility;
    },
    addEventListener: (type, cb) => listeners.push({ type, cb }),
  };
  const context = () => ({ url: 'https://shop.example/p.html', pageType: 'catalog-product-view', cache: 'HIT', release: null, ect: '4g' });
  const win = { addEventListener: (type, cb) => listeners.push({ type, cb }) };
  const c = createCollector({ vitals, send, win, doc, sampleRate, random: () => random, context });
  const pagehide = () => listeners.filter((l) => l.type === 'pagehide').forEach((l) => l.cb());
  const hide = () => {
    visibility = 'hidden';
    listeners.filter((l) => l.type === 'visibilitychange').forEach((l) => l.cb());
    visibility = 'visible';
  };
  return { c, handlers, send, hide, pagehide, vitals };
}

const metric = (name, id, value, extra = {}) => ({ name, id, value, delta: value, rating: 'good', navigationType: 'navigate', attribution: {}, ...extra });

describe('createCollector', () => {
  it('sends one text beacon with all metrics on hide', () => {
    const { c, handlers, send, hide } = setup();
    expect(c.start()).toBe(true);
    handlers.LCP(metric('LCP', 'l1', 1000));
    handlers.CLS(metric('CLS', 'c1', 0.01));
    handlers.TTFB(metric('TTFB', 't1', 200));
    hide();
    expect(send).toHaveBeenCalledTimes(1);
    const b = JSON.parse(send.mock.calls[0][0]);
    expect(b).toMatchObject({ v: 1, url: 'https://shop.example/p.html', pageType: 'catalog-product-view', cache: 'HIT', ect: '4g' });
    expect(b.metrics.map((m) => m.name)).toEqual(['LCP', 'CLS', 'TTFB']);
  });

  it('keeps the latest value per id and only re-sends what changed', () => {
    const { c, handlers, send, hide } = setup();
    c.start();
    handlers.CLS(metric('CLS', 'c1', 0.01));
    handlers.CLS(metric('CLS', 'c1', 0.05));
    handlers.LCP(metric('LCP', 'l1', 900));
    hide();
    expect(JSON.parse(send.mock.calls[0][0]).metrics).toHaveLength(2);
    expect(JSON.parse(send.mock.calls[0][0]).metrics[0].value).toBe(0.05);
    hide(); // nothing new: no beacon
    expect(send).toHaveBeenCalledTimes(1);
    handlers.CLS(metric('CLS', 'c1', 0.2)); // grew after the user came back
    handlers.LCP(metric('LCP', 'l2', 300, { navigationType: 'back-forward-cache' })); // bfcache restore
    hide();
    const second = JSON.parse(send.mock.calls[1][0]).metrics;
    expect(second.map((m) => [m.id, m.value])).toEqual([['c1', 0.2], ['l2', 300]]);
  });

  it('flushes on pagehide for never-visible pages, without double sends', () => {
    const { c, handlers, send, hide, pagehide } = setup();
    c.start();
    handlers.TTFB(metric('TTFB', 't1', 120));
    pagehide();
    expect(send).toHaveBeenCalledTimes(1);
    hide();
    pagehide();
    expect(send).toHaveBeenCalledTimes(1);
  });

  it('samples once per page view', () => {
    const out = setup({ random: 0.7, sampleRate: 0.5 });
    expect(out.c.sampled).toBe(false);
    expect(out.c.start()).toBe(false);
    expect(out.vitals.onLCP).not.toHaveBeenCalled();
    expect(setup({ random: 0.2, sampleRate: 0.5 }).c.sampled).toBe(true);
  });

  it('never throws when web-vitals, send or context fail', () => {
    const vitals = { onLCP: () => { throw new Error('x'); }, onINP: () => {}, onCLS: () => {}, onFCP: () => {}, onTTFB: () => {} };
    const doc = { visibilityState: 'hidden', addEventListener: () => {} };
    const c = createCollector({ vitals, send: () => { throw new Error('send'); }, win: { addEventListener: () => {} }, doc, sampleRate: 1, random: () => 0, context: () => { throw new Error('ctx'); } });
    expect(() => c.start()).not.toThrow();
    expect(() => c.record(null)).not.toThrow();
    c.record(metric('LCP', 'l1', 1));
    expect(c.flush()).toBe(false);
  });
});

describe('bundle', () => {
  it('is under 10 KB gzipped and uses text/plain sendBeacon', () => {
    const code = readFileSync(process.cwd() + '/../vector/public/rum.js');
    expect(gzipSync(code, { level: 9 }).length).toBeLessThan(10 * 1024);
    expect(code.toString()).toContain('text/plain');
    expect(code.toString()).not.toContain('application/json');
  });
});
