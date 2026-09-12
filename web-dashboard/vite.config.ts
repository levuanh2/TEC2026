import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // The default environment stays node: every test here is a pure function
  // except the few `*.dom.test.tsx` ones that must actually render, and those
  // opt in with a `@vitest-environment jsdom` docblock.
  test: { exclude: ['**/node_modules/**', 'tests/e2e/**'] },
})
