import { defineConfig } from '@playwright/test'

// This configuration deliberately does not load or contain credentials.  A
// developer enables it locally with REAL_E2E=true plus the gitignored
// REAL_E2E_EMAIL and REAL_E2E_PASSWORD variables.
// 5173 is the backend's explicitly allowed Vite origin. Keep the real test
// on that origin rather than weakening the frozen CORS policy for a test port.
const baseURL = process.env.REAL_E2E_BASE_URL ?? 'http://127.0.0.1:5173'

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: /(?:web-real-data|farmer-real-data|farmer-real-write|farmer-real-recommendations|farmer-real-cv|farmer-real-carbon-quickfix|farmer-real-straw-quickfix|round4-real|round41-real|sidebar-parity-real|round43-real|round44-real|round5-real|season-provisioning-real)\.spec\.ts/,
  // Generous: a local backend talking to hosted Supabase can take tens of
  // seconds per aggregate rollup query. Progressive per-section loading keeps
  // the page usable meanwhile, but the full click-through still needs headroom.
  timeout: 180_000,
  // One worker: every real spec signs in as the same shared QA identities, and
  // round4-real / sidebar-parity-real end by signing out, which Supabase does
  // with scope "global" — revoking the sessions of any spec running beside
  // them (seen as /auth/v1/user 403 → /v1/me 401 → "Phiên đăng nhập đã hết
  // hạn" mid-test when the suite ran on 8 workers).
  workers: 1,
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
  // A REAL_E2E_BASE_URL (e.g. the Render staging site, staging-e2e.yml) is an
  // already-deployed app: nothing local to start.
  webServer: process.env.REAL_E2E === 'true' && !process.env.REAL_E2E_BASE_URL
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
