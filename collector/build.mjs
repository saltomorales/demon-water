// Build the collector into one minified IIFE and enforce the 10 KB gzip budget.
// Output goes to vector/public/rum.js (served by the vector app on Upsun) so the
// Upsun build of the vector app, which only sees vector/, can serve it as-is.
import { build } from 'esbuild';
import { readFileSync, mkdirSync } from 'node:fs';
import { gzipSync } from 'node:zlib';

// Config constants: the ingest URL and the sampling rate (1 = every page view).
const ENDPOINT = process.env.RUM_ENDPOINT || 'https://ingest.main-bvxea6i-xeu4pm5hpww7u.eu-5.platformsh.site/rum';
const SAMPLE_RATE = Number(process.env.RUM_SAMPLE_RATE || '1');
const OUT = new URL('../vector/public/rum.js', import.meta.url).pathname;
const BUDGET_GZIP_BYTES = 10 * 1024;

mkdirSync(new URL('../vector/public/', import.meta.url).pathname, { recursive: true });

await build({
  entryPoints: [new URL('./src/index.js', import.meta.url).pathname],
  bundle: true,
  minify: true,
  format: 'iife',
  target: ['es2018'],
  legalComments: 'none',
  outfile: OUT,
  define: {
    __RUM_ENDPOINT__: JSON.stringify(ENDPOINT),
    __RUM_SAMPLE_RATE__: JSON.stringify(SAMPLE_RATE),
  },
});

const code = readFileSync(OUT);
const gz = gzipSync(code, { level: 9 }).length;
console.log(`rum.js: ${code.length} B raw, ${gz} B gzip (budget ${BUDGET_GZIP_BYTES} B)`);
if (gz > BUDGET_GZIP_BYTES) {
  console.error('Over the 10 KB gzip budget');
  process.exit(1);
}
