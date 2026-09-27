import { defineConfig } from '@playwright/test'

const ci = !!process.env.CI

// Mock-data suite: no backend, no Supabase, no credentials. Specs that sign in
// to the hosted project are excluded by name, not only by their own env
// guards, so a plain run can never select them: `*-real*.spec.ts` belong to
// playwright.real.config.ts, and redesign-qa.spec.ts -- a hosted, credentialed
// QA pass that does run through this config -- only with REDESIGN_QA=true.
const hostedSpecs = [/-real[-.]/, ...(process.env.REDESIGN_QA === 'true' ? [] : [/redesign-qa\.spec\.ts$/])]

export default defineConfig({
  testDir: './tests/e2e',
  testIgnore: hostedSpecs,
  forbidOnly: ci,
  // No retries: a mock-data test that needs one is a bug to fix, not to hide.
  retries: 0,
  workers: ci ? 2 : undefined,
  reporter: ci
    ? [['list'], ['junit', { outputFile: 'reports/playwright-junit.xml' }], ['html', { open: 'never', outputFolder: 'playwright-report' }]]
    : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    headless: true,
    browserName: 'chromium',
    channel: 'chrome',
    // Mock data only -- nothing secret can end up in a trace or screenshot.
    trace: ci ? 'retain-on-failure' : 'off',
    screenshot: ci ? 'only-on-failure' : 'off',
  },
  // VITE_API_BASE_URL is pinned to a closed port (9, "discard") so a developer's
  // .env can never point the mock suite at a real backend: the few API modules
  // that are not mock-gated yet fail fast instead (exception EXC-WEB-01).
  webServer: { command: 'npm run dev -- --host 127.0.0.1', url: 'http://127.0.0.1:5173', reuseExistingServer: !ci, env: { VITE_USE_MOCK_DATA: 'true', VITE_API_BASE_URL: 'http://127.0.0.1:9', VITE_SUPABASE_URL: '', VITE_SUPABASE_PUBLISHABLE_KEY: '' } },
})
