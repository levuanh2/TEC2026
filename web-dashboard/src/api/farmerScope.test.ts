import { afterEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken } from './client'
import { getFarmerScope } from './farms'

describe('getFarmerScope', () => {
  afterEach(() => { vi.unstubAllGlobals(); setAccessToken(null) })

  it('reads the whole hierarchy from one endpoint and maps the existing item shapes', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      farms: [{ id: 'f1', farm_code: 'F-01', farm_name: 'Hộ 1', province_name: 'Đồng Tháp', district_name: null, commune_name: null, plot_count: 1 }],
      plots: [{ id: 'p1', farm_id: 'f1', plot_code: 'P-01', name: 'Thửa 1', area_ha: 1.3, latitude: null, longitude: null }],
      crop_seasons: [{ id: 's1', plot_id: 'p1', season_code: 'HT-2026', crop_type: 'rice', variety_name: 'OM5451', planting_date: '2026-05-18', expected_harvest_date: null, actual_harvest_date: null, status: 'active' }],
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    setAccessToken('jwt')

    const scope = await getFarmerScope()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/v1\/farmer\/scope$/)
    expect(scope.farms[0]).toMatchObject({ id: 'f1', code: 'F-01', name: 'Hộ 1', plotCount: 1 })
    expect(scope.plots[0]).toMatchObject({ id: 'p1', farmId: 'f1', areaHa: 1.3 })
    expect(scope.seasons[0]).toMatchObject({ id: 's1', plotId: 'p1', name: 'HT-2026', harvestDate: null, status: 'active' })
  })
})
