import { defineConfig } from 'vitest/config'
import { loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

/** `<link rel="preconnect">` to the API and Supabase Auth, emitted only when
 * their build-time URLs are set. Measured from Vietnam to the API on EC2
 * (ap-southeast-2): TCP 0.33 s + TLS 0.33 s before a request can even be
 * sent; preconnecting overlaps that with the JS download instead of paying it
 * after the bundle runs. `crossorigin` because both are CORS fetches. */
function preconnect(urls: (string | undefined)[]): Plugin {
  const origins = [...new Set(urls.flatMap((u) => {
    try { return u ? [new URL(u).origin] : [] } catch { return [] }
  }))]
  return {
    name: 'agricarbon-preconnect',
    transformIndexHtml: () => origins.map((href) => ({
      tag: 'link', attrs: { rel: 'preconnect', href, crossorigin: '' }, injectTo: 'head-prepend' as const,
    })),
  }
}

export default defineConfig(({ mode }) => {
  // Same precedence Vite uses for import.meta.env: process env over .env files.
  const env = { ...loadEnv(mode, process.cwd(), 'VITE_'), ...process.env }
  return {
    plugins: [react(), preconnect([env.VITE_API_BASE_URL, env.VITE_SUPABASE_URL])],
    // Route chunks are lazy (src/routeChunks.ts). The dev server would compile
    // each on its first visit; warm them at start-up so a first navigation in
    // development (and the Playwright suite) does not wait on the transform.
    server: { warmup: { clientFiles: ['./src/farmer/FarmerExperience.tsx', './src/pages/*.tsx'] } },
    // The default environment stays node: every test here is a pure function
    // except the few `*.dom.test.tsx` ones that must actually render, and those
    // opt in with a `@vitest-environment jsdom` docblock.
    test: {
      exclude: ['**/node_modules/**', 'tests/e2e/**'],
      // Measured only with `--coverage` (CI does); a plain `npm test` stays fast.
      coverage: {
        provider: 'v8',
        include: ['src/**'],
        exclude: ['src/**/*.test.*', 'src/mocks/**'],
        reporter: ['text-summary', 'json-summary', 'lcov'],
      },
    },
  }
})
