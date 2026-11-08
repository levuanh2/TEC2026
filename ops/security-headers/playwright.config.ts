import { defineConfig } from '@playwright/test'

// F7 harness against the real production bundle (read-only; see csp.spec.ts).
// Not part of CI: it needs the live site. Real Chrome, one worker, no retries.
export default defineConfig({
  testDir: '.',
  testMatch: 'csp.spec.ts',
  retries: 0,
  workers: 1,
  reporter: 'list',
  timeout: 120_000,
  use: { baseURL: 'https://agricarbon.info.vn', headless: true, browserName: 'chromium', channel: 'chrome', trace: 'off' },
})
