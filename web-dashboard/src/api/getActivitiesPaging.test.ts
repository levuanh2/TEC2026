import { beforeEach, describe, expect, it, vi } from 'vitest'

/* Round 5.1 device UAT: a season with 27 activities showed only the newest 20
 * on Farmer and Management, because the client read page 1 of a paginated
 * endpoint. Every page must be read, and a page that says "no more" ends it. */
const calls: string[] = []
let total = 0
vi.mock('./farms', () => ({ usingMockData: false }))
vi.mock('./client', () => ({
  apiRequest: async (path: string) => {
    calls.push(path)
    const url = new URL(path, 'http://x')
    const page = Number(url.searchParams.get('page')), size = Number(url.searchParams.get('page_size'))
    const start = (page - 1) * size
    const items = Array.from({ length: Math.max(0, Math.min(size, total - start)) }, (_, i) => ({
      id: `a-${start + i}`, crop_season_id: 's', activity_type: 'irrigation', occurred_at: '2026-09-29T00:00:00Z', detail: {},
    }))
    return { items, page, page_size: size, total, has_more: start + size < total }
  },
}))

const { getActivities } = await import('./crops')

beforeEach(() => { calls.length = 0 })

describe('getActivities reads every page', () => {
  it.each([[0, 1], [20, 1], [27, 1], [100, 1], [101, 2], [250, 3]])('%i activities in %i request(s)', async (n, requests) => {
    total = n
    const out = await getActivities('s')
    expect(out).toHaveLength(n)
    expect(new Set(out.map((a) => a.id)).size).toBe(n)
    expect(calls).toHaveLength(requests)
    expect(calls.every((c) => c.includes('page_size=100'))).toBe(true)
  })
})
