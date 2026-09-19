import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react'

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
/** Monotonic per key, bumped on every change. Kept outside `store` so it also
 * survives `clearFarmerCache`, and so a reader can tell "nothing changed" from
 * "changed back to the same value". */
const seqs = new Map<string, number>()

export const STABLE_MS = 5 * 60_000
export const LIVE_MS = 20_000

function notify(key: string) {
  seqs.set(key, (seqs.get(key) ?? 0) + 1)
  listeners.get(key)?.forEach((fn) => fn())
}

/** How many times `key` has changed. The snapshot `useQuery` subscribes with. */
export const querySeq = (key: string): number => seqs.get(key) ?? 0

export function subscribeQuery(key: string, onChange: () => void): () => void {
  let set = listeners.get(key)
  if (!set) { set = new Set(); listeners.set(key, set) }
  set.add(onChange)
  return () => { set!.delete(onChange) }
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

/** Seasons whose records changed in this session. Read by
 * `scope.useRecommendations` to decide that a stored recommendation set is out
 * of date regardless of its age — a farmer who has just recorded something
 * should not wait 6h for the advice to catch up. */
const changedSeasons = new Set<string>()
export const seasonDataChanged = (seasonId: string) => changedSeasons.has(seasonId)
export const clearSeasonDataChanged = (seasonId: string) => { changedSeasons.delete(seasonId) }

export function clearFarmerCache(): void {
  store.clear()
  changedSeasons.clear()
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

/**
 * `enabled: false` reads the cache but never starts a request — used for work
 * that must not run as part of a page load (recommendation generation) and is
 * armed explicitly once the page is usable.
 */
export function useQuery<T>(key: string | null, fetcher: () => Promise<T>, staleMs = LIVE_MS, enabled = true): QueryState<T> {
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  /* `useSyncExternalStore`, not a subscribe-in-an-effect: a request started
   * before this component mounted (a prefetch, or another page's read of the
   * same key) can resolve between this render and an effect, and a hand-rolled
   * subscription drops that notification — which left the Home hero in its
   * skeleton forever, roughly one login in five, once the scope read began at
   * login instead of at mount. React re-reads the snapshot right after
   * subscribing, so that update cannot be missed. */
  const subscribe = useCallback(
    (onChange: () => void) => (key ? subscribeQuery(key, onChange) : () => undefined),
    [key],
  )
  useSyncExternalStore(subscribe, () => (key ? querySeq(key) : 0), () => 0)

  const e = key ? store.get(key) : undefined
  const version = e?.version ?? 0
  useEffect(() => {
    if (!key || !enabled) return
    fetchQuery(key, () => fetcherRef.current(), { staleMs }).catch(() => undefined)
  }, [key, version, staleMs, enabled])

  return {
    data: e?.data as T | undefined,
    error: e?.data === undefined ? e?.error : undefined,
    loading: Boolean(key) && enabled && e?.data === undefined && !e?.error,
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
   * engine + Carbon Engine evidence, measured 7-9.5s and 33 Supabase round
   * trips). It is never part of a page load: pages read the persisted items
   * with the cheap GET, and generation runs only when explicitly asked for or
   * when `scope.useRecommendations` arms it after the page is usable. Its own
   * cache key keeps concurrent sections (Home + Season) sharing one run. */
  recsGen: (seasonId: string) => `recsgen:${seasonId}`,
  cv: (seasonId: string) => `cv:${seasonId}`,
  carbon: (seasonId: string) => `carbon:${seasonId}`,
  /* Its own key under the `carbon:` prefix: an activity edit changes which
   * inputs are missing, but never the stored result. */
  carbonReadiness: (seasonId: string) => `carbon:${seasonId}:readiness`,
  org: (organizationId: string) => `org:${organizationId}`,
}

/** After a create/edit/delete: everything derived from that season's records —
 * and nothing that cannot have changed (viewer identity, farm/plot/season
 * hierarchy, organization), so one write does not cause a refetch storm.
 * Carbon readiness is included — an edited fertilizer or straw record can
 * resolve a missing input — but the stored Carbon result is not: only a
 * calculation changes it. */
export function markSeasonDataChanged(seasonId: string): void {
  changedSeasons.add(seasonId)
  invalidateQueries(keys.activities(seasonId), keys.metrics(seasonId), keys.recs(seasonId), keys.recsGen(seasonId), keys.carbonReadiness(seasonId))
}
