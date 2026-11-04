import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/* Link-intent prefetch: only the organisation-wide reads at the top of the
 * target route, each at most once while fresh, never a per-row fan-out. */

const calls: string[] = []
vi.mock('../api/carbon', () => ({ getOrganizationCarbonStatus: (o: string) => { calls.push(`carbon-status:${o}`); return Promise.resolve({ organization_id: o, items: [] }) } }))
vi.mock('../api/engine', () => ({ getEngineInfo: () => { calls.push('engine'); return Promise.resolve(null) } }))
vi.mock('../api/farms', () => ({
  listFarms: () => { calls.push('farms'); return Promise.resolve([]) },
  getOrganizationPlotsSeasons: (o: string) => { calls.push(`plots-seasons:${o}`); return Promise.resolve(new Map()) },
}))
vi.mock('../api/mrv', () => ({ getOrganizationMrvBatches: (o: string) => { calls.push(`mrv:${o}`); return Promise.resolve([]) } }))
vi.mock('../api/organizations', () => ({
  getOrganizationMetrics: (o: string) => { calls.push(`metrics:${o}`); return Promise.resolve({}) },
  getFarmPerformance: (o: string) => { calls.push(`farm-performance:${o}`); return Promise.resolve([]) },
}))

const { prefetchRouteData } = await import('./prefetch')
const { clearQueryCache, setQueryUser } = await import('./client')
const settle = () => new Promise((r) => setTimeout(r, 0))

beforeEach(() => { calls.length = 0; setQueryUser('manager') })
afterEach(() => clearQueryCache())

describe('prefetchRouteData', () => {
  it('an operations route warms the four organisation reads + engine, once while fresh', async () => {
    prefetchRouteData('/seasons?loc=all', 'org-1')
    await settle()
    expect(calls.sort()).toEqual(['carbon-status:org-1', 'engine', 'farms', 'mrv:org-1', 'plots-seasons:org-1'])
    calls.length = 0
    // Hovering another operations link while the cache is fresh costs nothing.
    prefetchRouteData('/carbon', 'org-1'); prefetchRouteData('/dashboard', 'org-1'); prefetchRouteData('/data-gaps', 'org-1')
    await settle()
    expect(calls).toEqual([])
  })

  it('/farms warms the farm list and the plots listing only', async () => {
    prefetchRouteData('/farms', 'org-1')
    await settle()
    expect(calls.sort()).toEqual(['farms', 'plots-seasons:org-1'])
  })

  it('/performance warms metrics and farm-performance only', async () => {
    prefetchRouteData('/performance', 'org-1')
    await settle()
    expect(calls.sort()).toEqual(['farm-performance:org-1', 'metrics:org-1'])
  })

  it('other routes, or no organisation, prefetch nothing', async () => {
    prefetchRouteData('/mrv', 'org-1')
    prefetchRouteData('/dashboard', null)
    await settle()
    expect(calls).toEqual([])
  })
})
