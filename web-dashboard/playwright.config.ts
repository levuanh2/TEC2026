import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  use: { baseURL: 'http://127.0.0.1:5173', headless: true, browserName: 'chromium', channel: 'chrome' },
  webServer: { command: 'npm run dev -- --host 127.0.0.1', url: 'http://127.0.0.1:5173', reuseExistingServer: true, env: { VITE_USE_MOCK_DATA: 'true', VITE_SUPABASE_URL: '', VITE_SUPABASE_PUBLISHABLE_KEY: '' } },
})
