import { useEffect, useReducer, useRef } from 'react'

/**
 * Farmer Web read cache: stale-while-revalidate with in-flight dedupe.
 *
 * - A key that already has data renders it immediately (no skeleton on
 *   revisit); the entry is re-fetched in the background once older than its
 *   `staleMs`. Mutable business reads (metrics, activities, recommendations,
 *   CV history) use a short window and are invalidated explicitly after a
 *   write, so they are never trusted indefinitely.
 * - Concurrent callers of the same key share one request (this also covers
 *   React StrictMode's double effect in dev).
 * - Everything is dropped on sign-out; nothing is persisted across tabs.
 */

type Entry = { data?: unknown; error?: string; at: number; promise?: Promise<unknown>; version: number }

const store = new Map<string, Entry>()
const listeners = new Map<string, Set<() => void>>()

export const STABLE_MS = 5 * 60_000
export const LIVE_MS = 20_000

function notify(key: string) {
  listeners.get(key)?.forEach((fn) => fn())
}

function entry(key: string): Entry {
  let e = store.get(key)
  if (!e) { e = { at: 0, version: 0 }; store.set(key, e) }
  return e
}

export function peekQuery<T>(key: string): T | undefined {
  return store.get(key)?.data as T | undefined
}

export function fetchQuery<T>(key: string, fetcher: () => Promise<T>, { staleMs = LIVE_MS, force = false }: { staleMs?: number; force?: boolean } = {}): Promise<T> {
  const e = entry(key)
  if (e.promise) return e.promise as Promise<T>
  if (!force && e.data !== undefined && Date.now() - e.at < staleMs) return Promise.resolve(e.data as T)
  const version = e.version
  const promise = fetcher().then(
    (data) => {
      const cur = entry(key)
      if (cur.version === version) { cur.data = data; cur.error = undefined; cur.at = Date.now() }
      if (cur.promise === promise) cur.promise = undefined
      notify(key)
      return data
    },
    (err: unknown) => {
      const cur = entry(key)
      if (cur.version === version) cur.error = err instanceof Error ? err.message : 'Không thể tải dữ liệu.'
      if (cur.promise === promise) cur.promise = undefined
      notify(key)
      throw err
    },
  )
  e.promise = promise
  e.error = undefined
  notify(key)
  return promise
}

/** Warm a key without surfacing errors — bounded to keys not already fresh or in flight. */
export function prefetchQuery<T>(key: string, fetcher: () => Promise<T>, staleMs = LIVE_MS): void {
  fetchQuery(key, fetcher, { staleMs }).catch(() => undefined)
}

/** Mark every key starting with one of `prefixes` stale; mounted readers refetch. */
export function invalidateQueries(...prefixes: string[]): void {
  for (const [key, e] of store) {
    if (!prefixes.some((p) => key.startsWith(p))) continue
    e.at = 0
    e.version += 1
    e.promise = undefined
    notify(key)
  }
}

/** Put a value produced elsewhere (e.g. a mutation response) into the cache;
 * any older in-flight request for this key can no longer overwrite it. */
export function setQueryData<T>(key: string, data: T): void {
  const e = entry(key)
  e.data = data
  e.error = undefined
  e.at = Date.now()
  e.version += 1
  e.promise = undefined
  notify(key)
}

export function clearFarmerCache(): void {
  store.clear()
  for (const key of listeners.keys()) notify(key)
}

export interface QueryState<T> {
  data?: T
  error?: string
  /** No data yet for this key (first load). */
  loading: boolean
  /** Showing cached data while a background refresh runs. */
  refreshing: boolean
  reload: () => void
}

export function useQuery<T>(key: string | null, fetcher: () => Promise<T>, staleMs = LIVE_MS): QueryState<T> {
  const [, rerender] = useReducer((n: number) => n + 1, 0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  useEffect(() => {
    if (!key) return
    let set = listeners.get(key)
    if (!set) { set = new Set(); listeners.set(key, set) }
    set.add(rerender)
    return () => { set!.delete(rerender) }
  }, [key])

  const e = key ? store.get(key) : undefined
  const version = e?.version ?? 0
  useEffect(() => {
    if (!key) return
    fetchQuery(key, () => fetcherRef.current(), { staleMs }).catch(() => undefined)
  }, [key, version, staleMs])

  return {
    data: e?.data as T | undefined,
    error: e?.data === undefined ? e?.error : undefined,
    loading: Boolean(key) && e?.data === undefined && !e?.error,
    refreshing: Boolean(e?.promise) && e?.data !== undefined,
    reload: () => { if (key) fetchQuery(key, () => fetcherRef.current(), { force: true }).catch(() => undefined) },
  }
}

export const keys = {
  scope: 'scope',
  activities: (seasonId: string) => `activities:${seasonId}`,
  metrics: (seasonId: string) => `metrics:${seasonId}`,
  recs: (seasonId: string) => `recs:${seasonId}`,
  /* Recommendation generation is an idempotent but expensive POST (rule
   * engine + Carbon Engine evidence, ~7s measured). Persisted items are read
   * with the cheap GET first; generation is cached under its own key so it
   * runs at most once per STABLE window per season, and again right after
   * that season's data changes. */
  recsGen: (seasonId: string) => `recsgen:${seasonId}`,
  cv: (seasonId: string) => `cv:${seasonId}`,
  carbon: (seasonId: string) => `carbon:${seasonId}`,
  org: (organizationId: string) => `org:${organizationId}`,
}

/** After a create/edit/delete: everything derived from that season's records. */
export function markSeasonDataChanged(seasonId: string): void {
  invalidateQueries(keys.activities(seasonId), keys.metrics(seasonId), keys.recs(seasonId), keys.recsGen(seasonId))
}
