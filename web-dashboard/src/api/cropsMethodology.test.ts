import { beforeEach, describe, expect, it, vi } from 'vitest'

// The module reads `usingMockData` from ./farms at import time, so both the mock
// flag and the transport are stubbed before `crops` is imported.
vi.mock('./farms', () => ({ usingMockData: false }))
const apiRequest = vi.fn()
vi.mock('./client', () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
  ApiError: class extends Error {},
}))

const { updateSeasonMethodology } = await import('./crops')

const serverSeason = {
  id: 's1', plot_id: 'p1', season_code: 'HT-2026', crop_type: 'rice', status: 'active',
  ipcc_water_regime: 'irrigated_multiple_drainage',
  pre_season_water_regime: 'non_flooded_pre_season_lt_180d',
  cultivation_days: 100,
}

const bodyOf = (call: unknown[]) => JSON.parse((call[1] as { body: string }).body)

beforeEach(() => {
  apiRequest.mockReset()
  apiRequest.mockResolvedValue(serverSeason)
})

describe('updateSeasonMethodology (PATCH /v1/crop-seasons/{id}/methodology)', () => {
  it('PATCHes only the keys the caller passed, in snake_case', async () => {
    await updateSeasonMethodology('s1', { ipccWaterRegime: 'upland' })
    const [path, init] = apiRequest.mock.calls[0]
    expect(path).toBe('/v1/crop-seasons/s1/methodology')
    expect((init as { method: string }).method).toBe('PATCH')
    expect(bodyOf(apiRequest.mock.calls[0])).toEqual({ ipcc_water_regime: 'upland' })
  })

  it('omits a field entirely rather than sending null for it', async () => {
    // An absent key keeps the stored value; sending null would clear it.
    await updateSeasonMethodology('s1', { cultivationDays: 95 })
    expect(bodyOf(apiRequest.mock.calls[0])).toEqual({ cultivation_days: 95 })
  })

  it('sends an explicit null when the caller clears a field', async () => {
    await updateSeasonMethodology('s1', { cultivationDays: null })
    expect(bodyOf(apiRequest.mock.calls[0])).toEqual({ cultivation_days: null })
  })

  it('does not turn a cleared cultivation length into 0', async () => {
    await updateSeasonMethodology('s1', { cultivationDays: null })
    expect(bodyOf(apiRequest.mock.calls[0]).cultivation_days).toBeNull()
    expect(bodyOf(apiRequest.mock.calls[0]).cultivation_days).not.toBe(0)
  })

  it('maps the response back to camelCase methodology fields', async () => {
    const season = await updateSeasonMethodology('s1', { ipccWaterRegime: 'irrigated_multiple_drainage' })
    expect(season.ipccWaterRegime).toBe('irrigated_multiple_drainage')
    expect(season.preSeasonWaterRegime).toBe('non_flooded_pre_season_lt_180d')
    expect(season.cultivationDays).toBe(100)
  })

  it('reports an unrecorded regime as null, never as an empty string', async () => {
    apiRequest.mockResolvedValue({ ...serverSeason, ipcc_water_regime: null, cultivation_days: null })
    const season = await updateSeasonMethodology('s1', {})
    expect(season.ipccWaterRegime).toBeNull()
    expect(season.cultivationDays).toBeNull()
  })

  it('sends an empty body when nothing was passed, so the season is left untouched', async () => {
    await updateSeasonMethodology('s1', {})
    expect(bodyOf(apiRequest.mock.calls[0])).toEqual({})
  })
})
