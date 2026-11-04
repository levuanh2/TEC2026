// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { withQuery } from '../test/withQuery'

/* /farms read every farm's plots one after another (1 + N sequential
 * requests — seen in production as eight 300 ms reads a second apart). It now
 * takes the areas from the organisation-wide plots+seasons listing: one
 * request, the same one the operations pages cache. The org page's slow
 * farm-performance table is read only once it nears the viewport. */

const calls = { farms: 0, listing: 0, perFarm: [] as string[], performance: 0 }
vi.mock('../api/farms', () => ({
  listFarms: () => { calls.farms++; return Promise.resolve(['a', 'b', 'c'].map((x) => ({ id: `farm-${x}`, code: x.toUpperCase(), name: `Hộ ${x}`, plotCount: 1 }))) },
  getOrganizationPlotsSeasons: () => {
    calls.listing++
    // farm-c is visible to this account but not part of the listing.
    return Promise.resolve(new Map([
      ['farm-a', { plots: [{ id: 'p1', farmId: 'farm-a', code: 'P1', name: 'T1', areaHa: 1.5 }], seasons: [] }],
      ['farm-b', { plots: [{ id: 'p2', farmId: 'farm-b', code: 'P2', name: 'T2', areaHa: 2 }], seasons: [] }],
    ]))
  },
  getPlotsForFarm: (id: string) => { calls.perFarm.push(id); return Promise.resolve([{ id: 'p3', farmId: id, code: 'P3', name: 'T3', areaHa: 0.25 }]) },
  getFarm: vi.fn(), getPlot: vi.fn(), getFarmMetrics: vi.fn(), getFarmCropSeasons: vi.fn(),
}))
vi.mock('../api/organizations', () => ({
  listOrganizations: () => Promise.resolve([{ id: 'org-1', name: 'HTX', code: 'H', organizationType: 'cooperative', isActive: true }]),
  getOrganization: () => Promise.resolve({ id: 'org-1', name: 'HTX', code: 'H', organizationType: 'cooperative', isActive: true }),
  getOrganizationSummary: () => Promise.resolve({ organizationId: 'org-1', farmCount: 3, plotCount: 3, cropSeasonCount: 0, totalAreaHa: 3.75, totalYieldKg: null, totalCo2eKg: null, co2ePerKg: null }),
  getFarmPerformance: () => { calls.performance++; return Promise.resolve([]) },
}))

/** An IntersectionObserver the test drives by hand. */
const observers: { cb: IntersectionObserverCallback; init?: IntersectionObserverInit; el?: Element }[] = []
class FakeIO {
  constructor(public cb: IntersectionObserverCallback, public init?: IntersectionObserverInit) { observers.push(this as never) }
  el?: Element
  observe(el: Element) { this.el = el }
  disconnect() {}
  unobserve() {}
  takeRecords() { return [] }
}

const { FarmsPage, OrganizationsPage } = await import('./directory')

beforeEach(() => { Object.assign(calls, { farms: 0, listing: 0, perFarm: [], performance: 0 }); observers.length = 0 })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('/farms areas', () => {
  it('one listing request for the organisation; only uncovered farms are read on their own', async () => {
    render(withQuery(<FarmsPage organizationId="org-1" />))
    await waitFor(() => expect(screen.getByText(/0,25/)).toBeTruthy())
    expect(calls.listing).toBe(1)
    expect(calls.perFarm).toEqual(['farm-c'])
    expect(screen.getByText(/1,5/)).toBeTruthy()
  })
})

describe('organisation page: farm-performance loads near the viewport', () => {
  it('is not requested until the table comes within 300 px, then exactly once', async () => {
    vi.stubGlobal('IntersectionObserver', FakeIO)
    render(withQuery(<OrganizationsPage />))
    await waitFor(() => expect(observers.length).toBeGreaterThan(0))
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    expect(calls.performance).toBe(0)
    const io = observers[observers.length - 1]
    expect(io.init?.rootMargin).toBe('300px 0px')
    act(() => io.cb([{ isIntersecting: true, target: io.el! } as IntersectionObserverEntry], io as never))
    await waitFor(() => expect(calls.performance).toBe(1))
  })
})
