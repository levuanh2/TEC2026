import { useEffect, useRef, useState, type RefObject } from 'react'
import { useQuery, type QueryKey } from '@tanstack/react-query'

/** What a page needs from a query, in the shape `Async` already renders —
 *  plus the two facts the old `useAsync` could not express: the data on
 *  screen is from an earlier read, and the latest refresh of it failed. */
export interface CachedState<T> {
  data?: T
  /** Only set when there is NO data to show. A failed refresh of data already
   *  on screen is `refreshError` instead — the page keeps rendering it. */
  error?: string
  loading: boolean
  /** A background refresh is running over data already on screen. */
  refreshing: boolean
  /** The last refresh failed; `data` is from `updatedAt`. */
  refreshError?: string
  updatedAt: number
  reload: () => void
}

const message = (e: unknown) => (e instanceof Error ? e.message : 'Không thể tải dữ liệu.')

export function useApiQuery<T>(
  key: QueryKey,
  fn: (signal: AbortSignal) => Promise<T>,
  options: { enabled?: boolean; staleTime?: number; abortOnLeave?: boolean } = {},
): CachedState<T> {
  const { enabled = true, staleTime, abortOnLeave = false } = options
  const q = useQuery({
    queryKey: key,
    // Reading `signal` is what tells the cache it may abort this request once
    // no screen wants it. Shared organisation-wide reads opt out: two
    // Management routes each mount their own observer, and aborting on the
    // hand-over would throw away a slow answer the next page is about to need.
    queryFn: abortOnLeave ? ({ signal }) => fn(signal) : () => fn(new AbortController().signal),
    enabled,
    ...(staleTime === undefined ? {} : { staleTime }),
  })
  const hasData = q.data !== undefined
  return {
    data: q.data,
    error: !hasData && q.error ? message(q.error) : undefined,
    // A disabled query that has never run is "waiting", which every caller
    // renders as loading; it never shows as an empty result.
    loading: !hasData && !q.error && (q.isPending || q.isFetching),
    refreshing: hasData && q.isFetching,
    refreshError: hasData && q.isRefetchError ? message(q.error) : undefined,
    updatedAt: q.dataUpdatedAt,
    reload: () => { void q.refetch() },
  }
}

/* ------------------------------------------------------- near-viewport */

/** The element that actually scrolls around `el`: the nearest ancestor with
 *  its own scrollbar, or null for the page viewport. Lazy sections inside a
 *  drawer or a scrolling panel must be observed against that box, not the
 *  window, or they would load only when the whole panel enters the window. */
export function scrollParent(el: Element | null): Element | null {
  for (let p = el?.parentElement ?? null; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
    const { overflowY } = getComputedStyle(p)
    if ((overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') && p.scrollHeight > p.clientHeight) return p
  }
  return null
}

export const PREFETCH_MARGIN = '300px 0px'

/** True once `ref` is within 300 px of its scroll container's visible area —
 *  and it stays true, so a section that loaded never unloads on scroll-away.
 *  Without IntersectionObserver (old browsers, jsdom) it is true at once: the
 *  data still loads, just not lazily. */
export function useNearViewport(ref: RefObject<Element | null>, rootMargin = PREFETCH_MARGIN): boolean {
  const [near, setNear] = useState(false)
  const done = useRef(false)
  useEffect(() => {
    if (done.current) return
    const el = ref.current
    if (!el || typeof IntersectionObserver === 'undefined') { done.current = true; setNear(true); return }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { done.current = true; setNear(true); io.disconnect() }
    }, { root: scrollParent(el), rootMargin })
    io.observe(el)
    return () => io.disconnect()
  }, [ref, rootMargin])
  return near
}
