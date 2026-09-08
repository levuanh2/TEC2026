import { afterEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken } from './client'
import { getFarm, getPlot, getPlotsForFarm, listFarms, usingMockData } from './farms'
import { getActivities, getCropSeason, getCropSeasons } from './crops'
import { getResourceMetrics } from './metrics'

// Xác nhận mapper đọc ĐÚNG field name thật của backend (docs/API_CATALOG.md,
// backend/schemas.py) — không phải field tưởng tượng. Response mẫu dưới đây copy
// nguyên field name từ FarmResponse/PlotResponse/CropSeasonResponse/
// ActivityResponse/MetricResponse trong backend/schemas.py.

function mockFetchOnce(body: unknown, status = 200) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })))
}

describe('hierarchy API mappers (real backend field shapes)', () => {
  afterEach(() => { vi.unstubAllGlobals(); setAccessToken(null) })

  it('usingMockData defaults to false when VITE_USE_MOCK_DATA is unset', () => {
    expect(usingMockData).toBe(false)
  })

  it('listFarms() maps FarmResponse (paginated) correctly', async () => {
    mockFetchOnce({ items: [{ id: 'f1', farm_code: 'HH-01', farm_name: 'Hộ A', province_name: 'Đồng Tháp', district_name: null, commune_name: null, plot_count: 3 }], page: 1, page_size: 20, total: 1, has_more: false })
    const farms = await listFarms()
    expect(farms).toEqual([{ id: 'f1', code: 'HH-01', name: 'Hộ A', province: 'Đồng Tháp', district: null, commune: null, plotCount: 3 }])
  })

  it('getFarm() maps a single FarmResponse', async () => {
    mockFetchOnce({ id: 'f1', farm_code: 'HH-01', farm_name: 'Hộ A', plot_count: 0 })
    const farm = await getFarm('f1')
    expect(farm?.plotCount).toBe(0)
  })

  it('getPlotsForFarm() maps PlotResponse items, latitude/longitude -> location string', async () => {
    mockFetchOnce({ items: [{ id: 'p1', farm_id: 'f1', plot_code: 'A-01', name: 'Thửa A', area_ha: 1.5, latitude: 10.1, longitude: 105.2 }] })
    const plots = await getPlotsForFarm('f1')
    expect(plots[0].location).toBe('10.1, 105.2')
  })

  it('getPlot() with null latitude leaves location undefined (not "null, null")', async () => {
    mockFetchOnce({ id: 'p1', farm_id: 'f1', plot_code: 'A-01', name: 'Thửa A', area_ha: 1.5, latitude: null, longitude: null })
    const plot = await getPlot('p1')
    expect(plot?.location).toBeUndefined()
  })

  it('getCropSeasons() maps CropSeasonResponse field names (season_code -> name)', async () => {
    mockFetchOnce({ items: [{ id: 's1', plot_id: 'p1', season_code: 'HT-2026', crop_type: 'rice', variety_name: 'OM5451', planting_date: '2026-05-18', expected_harvest_date: null, actual_harvest_date: null, status: 'active' }] })
    const seasons = await getCropSeasons('p1')
    expect(seasons[0]).toMatchObject({ id: 's1', plotId: 'p1', name: 'HT-2026', variety: 'OM5451', harvestDate: null })
  })

  it('getCropSeason() maps a single CropSeasonResponse', async () => {
    mockFetchOnce({ id: 's1', plot_id: 'p1', season_code: 'HT-2026', crop_type: 'rice', status: 'active' })
    const season = await getCropSeason('s1')
    expect(season?.name).toBe('HT-2026')
  })

  it('getActivities() maps ActivityResponse (paginated) — payload stays JSON for detail column', async () => {
    mockFetchOnce({ items: [{ id: 'a1', activity_type: 'irrigation', occurred_at: '2026-09-02T06:30:00Z', recorded_at: '2026-09-02T06:31:00Z', recorded_by: 'Nguyễn Văn An', source: 'mobile_offline', payload: { water_volume_m3: 32, note: null } }], page: 1, page_size: 20, total: 1, has_more: false })
    const activities = await getActivities('s1')
    expect(activities[0].type).toBe('irrigation')
    expect(activities[0].detail).toContain('water_volume_m3')
  })

  it('getResourceMetrics() reads MetricResponse field names, keeps null as null (never 0)', async () => {
    mockFetchOnce({ yield_kg: null, water_m3: 12.5, fertilizer_kg: 40, total_co2e_kg: null, water_per_kg: null, fertilizer_per_kg: null, co2e_per_kg: null, cost_per_kg: null, data_completeness: { water: true, fertilizer: true, cost: false, carbon: false } })
    const metrics = await getResourceMetrics('s1')
    expect(metrics.waterPerKg).toBeNull()
    expect(metrics.fertilizerPerKg).toBeNull()
    expect(metrics.costPerKg).toBeNull()
  })
})
