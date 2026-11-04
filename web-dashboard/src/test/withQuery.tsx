import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

/** A fresh, isolated query cache per test: no retries (a test's failure is
 *  final), no garbage-collection timers left running after the test. */
export function testQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } })
}

export function withQuery(ui: ReactNode, client: QueryClient = testQueryClient()) {
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>
}

export function queryWrapper(client: QueryClient = testQueryClient()) {
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
