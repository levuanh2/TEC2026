import { defineConfig } from '@playwright/test'

// This configuration deliberately does not load or contain credentials.  A
// developer enables it locally with REAL_E2E=true plus the gitignored
// REAL_E2E_EMAIL and REAL_E2E_PASSWORD variables.
// 5173 is the backend's explicitly allowed Vite origin. Keep the real test
// on that origin rather than weakening the frozen CORS policy for a test port.
const baseURL = process.env.REAL_E2E_BASE_URL ?? 'http://127.0.0.1:5173'

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: /(?:web-real-data|farmer-real-data|farmer-real-write|farmer-real-recommendations|farmer-real-cv|farmer-real-carbon-quickfix|farmer-real-straw-quickfix)\.spec\.ts/,
  // Generous: a local backend talking to hosted Supabase can take tens of
  // seconds per aggregate rollup query. Progressive per-section loading keeps
  // the page usable meanwhile, but the full click-through still needs headroom.
  timeout: 180_000,
  expect: { timeout: 60_000 },
  use: {
    baseURL,
    headless: true,
    channel: 'chrome',
    // Real specs type a real (demo/QA) password. A retained trace records
    // every fill() value, so traces stay off; the password field is
    // type=password, so a failure screenshot shows only masked dots.
    screenshot: 'only-on-failure',
    trace: 'off',
  },
  // Do not start a normal dashboard server for a skipped test.  When enabled,
  // compile an explicit real-data build; VITE_USE_MOCK_DATA remains false.
  webServer: process.env.REAL_E2E === 'true'
    ? {
        command: 'npm run dev -- --host 127.0.0.1 --port 5173',
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        env: {
          VITE_USE_MOCK_DATA: 'false',
          ...(process.env.REAL_E2E_API_BASE_URL ? { VITE_API_BASE_URL: process.env.REAL_E2E_API_BASE_URL } : {}),
        },
      }
    : undefined,
})
