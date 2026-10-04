import { beforeEach, describe, expect, it, vi } from 'vitest'

/* Round 5.1 one-request reads: Home reads only the newest records plus the
 * server's whole-season summary, and Management reads every farm's plots and
 * seasons, and every MRV case's batches, in one request each. The client only
 * maps the server's shapes -- no counting, no summing. */
const calls: string[] = []
let reply: unknown
vi.mock('./client', () => ({
  apiRequest: async (path: string) => { calls.push(path); return reply },
}))

const { getRecentActivities, getActivitySummary } = await import('./crops')
const { getOrganizationPlotsSeasons } = await import('./farms')
const { getOrganizationMrvBatches } = await import('./mrv')

beforeEach(() => { calls.length = 0 })

describe('getRecentActivities', () => {
  it('reads one page of exactly `limit` rows (the endpoint is newest first)', async () => {
    reply = { items: [
      { id: 'a2', activity_type: 'harvest', occurred_at: '2026-09-02T00:00:00Z', payload: { yield_kg: 10 }, recorded_by: 'Lan', source: 'web' },
      { id: 'a1', activity_type: 'irrigation', occurred_at: '2026-09-01T00:00:00Z', payload: {}, recorded_by: null, source: 'mobile_offline' },
    ] }
    const out = await getRecentActivities('s-1', 5)
    expect(calls).toEqual(['/v1/crop-seasons/s-1/activities?page=1&page_size=5'])
    expect(out.map((a) => [a.id, a.type, a.recorder, a.source])).toEqual([
      ['a2', 'harvest', 'Lan', 'web'], ['a1', 'irrigation', '—', 'mobile_offline'],
    ])
    expect(JSON.parse(out[0].detail)).toEqual({ yield_kg: 10 })
  })
})

describe('getActivitySummary', () => {
  it('maps the server summary and turns decimal strings into numbers', async () => {
    reply = {
      total: 7, count_by_type: { harvest: 2, irrigation: 5 },
      cost_by_type: { irrigation: { records: 5, with_cost: 3, recorded_vnd: '150000.50' } },
      harvests: 2, harvests_with_area: 1, harvested_area_ha: '0.75', fertilizer_has_nutrient: 1,
      first_seeding_at: '2026-06-01T00:00:00Z', last_harvest_at: '2026-09-01T00:00:00Z',
    }
    const s = await getActivitySummary('s-1')
    expect(calls).toEqual(['/v1/crop-seasons/s-1/activity-summary'])
    expect(s).toEqual({
      total: 7, countByType: { harvest: 2, irrigation: 5 },
      costByType: { irrigation: { records: 5, withCost: 3, recordedVnd: 150000.5 } },
      harvests: 2, harvestsWithArea: 1, harvestedAreaHa: 0.75, fertilizerHasNutrient: true,
      firstSeedingAt: '2026-06-01T00:00:00Z', lastHarvestAt: '2026-09-01T00:00:00Z',
    })
  })

  it('an empty season: missing maps are empty and missing dates are null, never invented', async () => {
    reply = { total: 0, harvests: 0, harvests_with_area: 0, harvested_area_ha: 0, fertilizer_has_nutrient: false }
    const s = await getActivitySummary('s-2')
    expect(s.countByType).toEqual({})
    expect(s.costByType).toEqual({})
    expect(s.firstSeedingAt).toBeNull()
    expect(s.lastHarvestAt).toBeNull()
    expect(s.fertilizerHasNutrient).toBe(false)
  })
})

describe('getOrganizationPlotsSeasons', () => {
  it('one request; per farm the same plots and seasons the per-farm routes return', async () => {
    reply = { organization_id: 'o-1', items: [
      { farm_id: 'f-1',
        plots: [{ id: 'p-1', farm_id: 'f-1', plot_code: 'P1', name: 'Ruộng 1', area_ha: 1.2, latitude: 10.1, longitude: 105.2 }],
        crop_seasons: [{ id: 's-1', plot_id: 'p-1', season_code: 'HT-2026', variety_name: 'OM5451', planting_date: '2026-06-01',
          actual_harvest_date: null, status: 'active', ipcc_water_regime: 'awd' }] },
      { farm_id: 'f-2', plots: [], crop_seasons: [] },
    ] }
    const byFarm = await getOrganizationPlotsSeasons('o-1')
    expect(calls).toEqual(['/v1/organizations/o-1/plots-seasons'])
    expect([...byFarm.keys()]).toEqual(['f-1', 'f-2'])
    const f1 = byFarm.get('f-1')!
    expect(f1.plots).toEqual([{ id: 'p-1', farmId: 'f-1', code: 'P1', name: 'Ruộng 1', areaHa: 1.2, location: '10.1, 105.2' }])
    expect(f1.seasons[0]).toMatchObject({ id: 's-1', plotId: 'p-1', name: 'HT-2026', status: 'active', ipccWaterRegime: 'awd',
      preSeasonWaterRegime: null, cultivationDays: null, expectedHarvestDate: undefined })
    expect(byFarm.get('f-2')).toEqual({ plots: [], seasons: [] })
  })
})

describe('getOrganizationMrvBatches', () => {
  it('every case with its batches, mapped like listMrvBatches', async () => {
    reply = { organization_id: 'o-1', items: [
      { case_id: 'c-1', case_code: 'MRV-1', status: 'draft', batches: [
        { production_batch_id: 'b-1', batch_code: 'default', crop_season_id: 's-1', farm_id: 'f-1', plot_id: 'p-1' }] },
      { case_id: 'c-2', case_code: 'MRV-2', status: 'submitted', batches: [] },
    ] }
    const cases = await getOrganizationMrvBatches('o-1')
    expect(calls).toEqual(['/v1/organizations/o-1/mrv-batches'])
    expect(cases).toEqual([
      { caseId: 'c-1', caseCode: 'MRV-1', status: 'draft',
        batches: [{ productionBatchId: 'b-1', batchCode: 'default', cropSeasonId: 's-1', farmId: 'f-1', plotId: 'p-1' }] },
      { caseId: 'c-2', caseCode: 'MRV-2', status: 'submitted', batches: [] },
    ])
  })
})
