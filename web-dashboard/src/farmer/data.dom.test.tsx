// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearFarmerCache, fetchQuery, useQuery } from './data'

/* `useQuery` rendering against reads that started before the reader mounted —
 * the shape a prefetch produces.
 *
 * Background: `useQuery` used to subscribe from a `useEffect`. React commits a
 * render first and flushes passive effects afterwards, so a request begun
 * earlier could resolve inside that window, its notification would go out with
 * no listener attached, and the component stayed `loading` forever. The
 * follow-up effect could not rescue it either, because `fetchQuery` finds the
 * key fresh and resolves from cache without notifying again. It showed up as
 * the Home hero stuck in its skeleton, roughly one login in five, once the
 * Farmer scope read moved to login time. `useQuery` now subscribes through
 * `useSyncExternalStore`, which re-reads the snapshot right after subscribing.
 *
 * HONEST LIMIT OF THESE TESTS: they do not reproduce that window, and they
 * pass against the old implementation too. React flushes passive effects
 * synchronously under `act`/`flushSync`, so in jsdom the gap between commit and
 * effect does not exist and the notification can never be missed — verified
 * directly (`render -> passive-effect -> after-flushSync`). What is covered
 * here is `useQuery`'s actual rendering behaviour for prefetched reads; the
 * store-level invariant the fix relies on is asserted in `data.test.ts` ("a
 * change that lands before a subscriber attaches is still visible to it"), and
 * the fix itself was verified in a real browser — 1-in-5 logins stuck before,
 * 6/6 clean after. */

function Reader({ queryKey, fetcher }: { queryKey: string; fetcher: () => Promise<string> }) {
  const { data, loading } = useQuery(queryKey, fetcher)
  return <p>{loading ? 'skeleton' : (data ?? 'no data')}</p>
}

describe('useQuery rendering', () => {
  beforeEach(() => clearFarmerCache())
  // vitest runs without globals, so testing-library's auto-cleanup is not
  // registered for us — unmount explicitly or renders pile up in one document.
  afterEach(() => { cleanup(); clearFarmerCache() })

  it('renders a prefetched value immediately, with no second request', async () => {
    const fetcher = vi.fn(() => Promise.resolve('prefetched'))
    await fetchQuery('k', fetcher, { staleMs: 60_000 })

    render(<Reader queryKey="k" fetcher={fetcher} />)

    expect(screen.getByText('prefetched')).toBeTruthy()
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('joins a prefetch that is still in flight instead of starting its own', async () => {
    let resolve!: (v: string) => void
    const fetcher = vi.fn(() => new Promise<string>((r) => { resolve = r }))
    void fetchQuery('k', fetcher)          // started by someone else

    render(<Reader queryKey="k" fetcher={fetcher} />)
    expect(screen.getByText('skeleton')).toBeTruthy()

    await act(async () => { resolve('warmed value') })

    await waitFor(() => expect(screen.getByText('warmed value')).toBeTruthy())
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('renders an update that arrives after mount', async () => {
    let resolve!: (v: string) => void
    render(<Reader queryKey="k" fetcher={() => new Promise<string>((r) => { resolve = r })} />)
    expect(screen.getByText('skeleton')).toBeTruthy()
    await act(async () => { resolve('later value') })
    await waitFor(() => expect(screen.getByText('later value')).toBeTruthy())
  })

  it('two readers of one key share a single request and both render it', async () => {
    let resolve!: (v: string) => void
    const fetcher = vi.fn(() => new Promise<string>((r) => { resolve = r }))
    render(
      <>
        <Reader queryKey="k" fetcher={fetcher} />
        <Reader queryKey="k" fetcher={fetcher} />
      </>,
    )
    await act(async () => { resolve('shared value') })
    await waitFor(() => expect(screen.getAllByText('shared value')).toHaveLength(2))
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})
