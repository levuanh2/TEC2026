import { afterAll, describe, expect, it, vi } from 'vitest'

/* Mock mode (VITE_USE_MOCK_DATA=true, the Playwright mock suite and demos)
 * answers the Round 5.1 reads from the local fixtures with the same shapes,
 * without any network call. */
vi.stubEnv('VITE_USE_MOCK_DATA', 'true')
const apiRequest = vi.fn()
vi.mock('./client', () => ({ apiRequest: (...a: unknown[]) => apiRequest(...a) }))

const { getRecentActivities, getActivitySummary } = await import('./crops')
const { getOrganizationPlotsSeasons } = await import('./farms')
const { activities, cropSeasons, farms, plots } = await import('../mocks/data')

afterAll(() => { vi.unstubAllEnvs() })

const seasonWithMost = () => {
  const counts = new Map<string, number>()
  for (const a of activities) counts.set(a.cropSeasonId, (counts.get(a.cropSeasonId) ?? 0) + 1)
  return [...counts.entries()].sort((x, y) => y[1] - x[1])[0][0]
}

describe('mock mode', () => {
  it('recent activities: newest first, at most `limit`', async () => {
    const id = seasonWithMost()
    const out = await getRecentActivities(id, 2)
    const own = activities.filter((a) => a.cropSeasonId === id)
    expect(out).toHaveLength(Math.min(2, own.length))
    const newest = [...own].map((a) => a.occurredAt).sort().reverse().slice(0, 2)
    expect(out.map((a) => a.occurredAt)).toEqual(newest)
  })

  it('activity summary is counted from the fixtures: totals, per type, first seeding and last harvest', async () => {
    const id = seasonWithMost()
    const own = activities.filter((a) => a.cropSeasonId === id)
    const s = await getActivitySummary(id)
    expect(s.total).toBe(own.length)
    expect(Object.values(s.countByType).reduce((x, y) => x + y, 0)).toBe(own.length)
    const seeding = own.filter((a) => a.type === 'seeding').map((a) => a.occurredAt).sort()
    const harvest = own.filter((a) => a.type === 'harvest').map((a) => a.occurredAt).sort()
    expect(s.firstSeedingAt).toBe(seeding[0] ?? null)
    expect(s.lastHarvestAt).toBe(harvest.at(-1) ?? null)
    expect(s.harvests).toBe(harvest.length)
    // No cost / area facts are invented in mock mode.
    expect(s.costByType).toEqual({})
    expect(s.harvestedAreaHa).toBe(0)
  })

  it('a season with no records: an empty summary, not an error', async () => {
    const s = await getActivitySummary('no-such-season')
    expect(s).toMatchObject({ total: 0, harvests: 0, firstSeedingAt: null, lastHarvestAt: null })
  })

  it('organization plots/seasons: every farm, its own plots and their seasons only', async () => {
    const byFarm = await getOrganizationPlotsSeasons('any-org')
    expect([...byFarm.keys()].sort()).toEqual(farms.map((f) => f.id).sort())
    for (const f of farms) {
      const entry = byFarm.get(f.id)!
      expect(entry.plots).toEqual(plots.filter((p) => p.farmId === f.id))
      const ids = new Set(entry.plots.map((p) => p.id))
      expect(entry.seasons).toEqual(cropSeasons.filter((s) => ids.has(s.plotId)))
    }
    expect(apiRequest).not.toHaveBeenCalled()
  })
})
