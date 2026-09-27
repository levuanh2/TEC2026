import { expect, test as base } from '@playwright/test'

export { expect }
export type { Page } from '@playwright/test'

/* Every mock-data spec imports `test` from here instead of '@playwright/test'.
 * The auto fixture below fails a test on anything the page reports as broken
 * while it ran:
 *   - console.error
 *   - an uncaught exception / unhandled promise rejection (pageerror)
 *   - a request that failed at the network level (DNS, CORS, abort)
 *   - any HTTP 4xx/5xx response (mock mode makes no data requests over HTTP)
 * Mock mode serves data in-process, so a healthy run produces none of these.
 *
 * Exceptions are EXACT strings, each with a reason (docs/CI_PIPELINE.md, "CI
 * exceptions"). No patterns, no blanket console suppression. */
// EXC-WEB-01: api/carbon.ts (carbon + readiness), api/engine.ts (/health) and
// api/organizations.ts are not mock-gated yet, so in mock mode they call the
// API. playwright.config.ts pins that API to 127.0.0.1:9, a port Chrome refuses
// itself (ERR_UNSAFE_PORT): nothing ever reaches a network or a developer's
// backend. Only these exact requests are tolerated; any other escaped request,
// and any other console error, still fails. Follow-up: mock-gate the three modules.
const UNSAFE = 'net::ERR_UNSAFE_PORT'
const ALLOWED: { text: string; reason: string }[] = [
  ...['crop-demo-01', 'crop-demo-02'].flatMap((id) => [
    { text: `requestfailed: GET http://127.0.0.1:9/v1/crop-seasons/${id}/carbon/readiness (${UNSAFE})`, reason: 'EXC-WEB-01' },
    { text: `requestfailed: GET http://127.0.0.1:9/v1/crop-seasons/${id}/carbon?scenario=as_recorded (${UNSAFE})`, reason: 'EXC-WEB-01' },
  ]),
  { text: `requestfailed: GET http://127.0.0.1:9/health (${UNSAFE})`, reason: 'EXC-WEB-01' },
  { text: `requestfailed: GET http://127.0.0.1:9/v1/organizations (${UNSAFE})`, reason: 'EXC-WEB-01' },
  // Chrome's console line for the same blocked requests carries no URL; the
  // unsafe-port error can only come from the pinned address above.
  { text: `console.error: Failed to load resource: ${UNSAFE}`, reason: 'EXC-WEB-01' },
]

export const test = base.extend<{ pageHealth: void }>({
  pageHealth: [
    async ({ page }, use, testInfo) => {
      const problems: string[] = []
      const record = (kind: string, text: string) => {
        const line = `${kind}: ${text}`
        if (!ALLOWED.some((a) => a.text === line)) problems.push(line)
      }
      page.on('console', (msg) => {
        if (msg.type() === 'error') record('console.error', msg.text())
      })
      page.on('pageerror', (err) => record('pageerror', `${err.name}: ${err.message}`))
      page.on('requestfailed', (req) => {
        // Navigating away aborts in-flight requests; that is not a failure.
        if (req.failure()?.errorText === 'net::ERR_ABORTED') return
        record('requestfailed', `${req.method()} ${req.url()} (${req.failure()?.errorText})`)
      })
      page.on('response', (res) => {
        // Mock mode answers data calls in-process: any HTTP error response is
        // either a missing asset or a request that escaped the mock layer.
        if (res.status() >= 400) record(`http${res.status()}`, `${res.request().method()} ${res.url()}`)
      })
      await use()
      if (problems.length) {
        await testInfo.attach('page-health.txt', { body: problems.join('\n'), contentType: 'text/plain' })
      }
      expect(problems, 'unexpected console errors / page errors / failed requests').toEqual([])
    },
    { auto: true },
  ],
})
