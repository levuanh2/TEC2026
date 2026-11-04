import { QueryClient, type QueryKey } from '@tanstack/react-query'
import { isTransientError, setWriteListener } from '../api/client'

/* One in-memory query cache for the Management web app.
 *
 * - Nothing is persisted: the cache lives in this tab's memory and is dropped
 *   whole when a session ends or a different person signs in (`clearQueryCache`).
 * - Every key starts with the signed-in user (`scope()`), so even a missed
 *   clear can never hand one account's rows to another.
 * - Errors are never cached as data. A failed refetch keeps the last good data
 *   on screen and the page says it may be out of date (see `staleNotice`).
 */

/** Business data (seasons, Carbon status, rollups): fresh for 45 s. */
export const BUSINESS_STALE_MS = 45_000
/** Organisation identity, engine version — changes on admin action/deploy. */
export const METADATA_STALE_MS = 5 * 60_000
/** Unused entries stay in memory this long (back navigation is instant). */
export const GC_MS = 10 * 60_000
/** Automatic retries of a transient read failure (network, 502/503/504). */
export const MAX_RETRIES = 2

export function retryDelay(attempt: number): number {
  // 1 s, then 3 s, plus jitter so many tabs do not retry in lock-step.
  const base = attempt === 0 ? 1000 : 3000
  return base + Math.floor(Math.random() * 400)
}

export function shouldRetry(failureCount: number, error: unknown): boolean {
  return failureCount < MAX_RETRIES && isTransientError(error)
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: BUSINESS_STALE_MS,
        gcTime: GC_MS,
        retry: shouldRetry,
        retryDelay,
        // A focus refetch of every heavy rollup is exactly the burst the small
        // backend could not take; stale data refreshes on the next mount/visit.
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
      },
      // Writes are never retried automatically: whether one landed is unknown.
      mutations: { retry: false },
    },
  })
}

export const queryClient = makeQueryClient()

/* ----------------------------------------------------------------- scope */

let scopeUser: string | null = null

/** Called by the auth module whenever the signed-in user is known. A change of
 *  user drops everything the previous one loaded. */
export function setQueryUser(userId: string | null): void {
  if (userId !== scopeUser) queryClient.clear()
  scopeUser = userId
}

/** Session end: cancel what is in flight and forget every cached answer. */
export function clearQueryCache(): void {
  void queryClient.cancelQueries()
  queryClient.clear()
  scopeUser = null
}

/** Prefix of every key: whose data this is. */
export function scope(): readonly ['u', string] {
  return ['u', scopeUser ?? 'anonymous'] as const
}

export const keys = {
  org: (orgId: string, resource: string, ...rest: unknown[]): QueryKey => [...scope(), 'org', orgId, resource, ...rest],
  orgMeta: (orgId: string): QueryKey => [...scope(), 'org', orgId, 'meta'],
  organizations: (): QueryKey => [...scope(), 'organizations'],
  farms: (): QueryKey => [...scope(), 'farms'],
  farm: (farmId: string, resource: string): QueryKey => [...scope(), 'farm', farmId, resource],
  engine: (): QueryKey => ['engine'],
}

/** After a write: everything organisation- or farm-wide may have changed. */
export function invalidateOrganizationData(): Promise<void> {
  const s = scope()
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: [...s, 'org'] }),
    queryClient.invalidateQueries({ queryKey: [...s, 'farms'] }),
    queryClient.invalidateQueries({ queryKey: [...s, 'farm'] }),
  ]).then(() => undefined)
}

// Any successful write marks the organisation/farm reads stale; screens that
// are open refetch now, the rest on their next visit.
setWriteListener(() => { void invalidateOrganizationData() })
