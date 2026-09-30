// @vitest-environment jsdom
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CarbonSeasonStatus } from '../api/carbon'
import { carbonView } from '../carbon/readiness'

/* Round 5.1: Management reads every season's Carbon state with ONE request.
 * Before, `useOperations` asked for readiness and the actual result once per
 * season (2 × N requests). Now the count is one, whatever N is; each row is
 * the same view the per-season path produced; and a season whose status
 * failed — or is missing — is an error on that row only. */

type StatusBody = { organization_id: string; items: CarbonSeasonStatus[] }
/* A plain recorder rather than a vi.fn spy: every call is counted, and the
 * answer (resolved or rejected) is created only when the hook asks. */
const calls: string[] = []
let respond: (org: string) => Promise<StatusBody> = () => Promise.reject(new Error('not set'))
let seasons: { id: string; plotId: string; name: string; status: string }[] = []

vi.mock('../api/carbon', () => ({ getOrganizationCarbonStatus: (org: string) => { calls.push(org); return respond(org) } }))
vi.mock('../api/engine', () => ({ getEngineInfo: () => Promise.resolve({ efConfigVersion: 'v1', engineVersion: 'e', carbonProductionReady: false }) }))
vi.mock('../api/mrv', () => ({ listMrvCases: () => Promise.resolve([]), listMrvBatches: () => Promise.resolve([]) }))
const listingCalls: string[] = []
const perFarmCalls: string[] = []
vi.mock('../api/farms', () => ({
  listFarms: () => Promise.resolve([{ id: 'farm-1', code: 'F1', name: 'Nông hộ 1', plotCount: 1 }, { id: 'farm-2', code: 'F2', name: 'Nông hộ 2', plotCount: 1 }]),
  getOrganizationPlotsSeasons: (org: string) => {
    listingCalls.push(org)
    return Promise.resolve(new Map(['farm-1', 'farm-2'].map((farmId) => [farmId, {
      plots: [{ id: `plot-${farmId}`, farmId, code: 'P', name: 'Thửa' }],
      seasons: seasons.filter((_, i) => (i % 2 ? 'farm-2' : 'farm-1') === farmId),
    }])))
  },
  getFarmCropSeasons: (farmId: string) => { perFarmCalls.push(farmId); return Promise.resolve([]) },
  getPlotsForFarm: (farmId: string) => { perFarmCalls.push(farmId); return Promise.resolve([]) },
}))

const { useOperations } = await import('./ops')

const readiness = (canCalculate: boolean) => ({
  can_calculate: canCalculate, blocking_count: canCalculate ? 0 : 1, input_hash: 'h1', ef_config_version: 'v1',
  missing_inputs: canCalculate ? [] : [{ code: 'yield', label: 'Sản lượng thu hoạch', detail: 'Chưa có', flow: 'activity' as const, activity_type: 'harvest', blocking: true }],
})
const actual = (id: string) => ({
  calculation_id: `calc-${id}`, crop_season_id: id, scenario: 'as_recorded' as const, calculation_kind: 'actual' as const,
  total_co2e_kg: 4877.77, co2e_per_kg: 0.813, input_hash: 'h1', ef_config_version: 'v1', calculated_at: '2026-09-29T07:00:00Z', breakdown: [], warnings: [],
})
function item(id: string, n: number): CarbonSeasonStatus {
  const ready = n % 3 !== 1
  return { crop_season_id: id, readiness: readiness(ready), readiness_error: null, actual: ready && n % 3 === 0 ? actual(id) : null, actual_error: null }
}
function useSeasons(n: number) {
  seasons = Array.from({ length: n }, (_, i) => ({ id: `s-${i}`, plotId: `plot-farm-${(i % 2) + 1}`, name: `Vụ ${i}`, status: 'active' }))
  return seasons.map((s, i) => item(s.id, i))
}

async function settle() {
  const hook = renderHook(() => useOperations('org-1'))
  await waitFor(() => expect(hook.result.current.data?.pending).toBe(0))
  await waitFor(() => expect(hook.result.current.loading).toBe(false))
  return hook.result.current.data!
}

beforeEach(() => { calls.length = 0; listingCalls.length = 0; perFarmCalls.length = 0 })
afterEach(cleanup)

describe('Management Carbon state in one request', () => {
  it.each([1, 6, 25])('asks once for %i season(s), and each row is the per-season view', async (n) => {
    const items = useSeasons(n)
    respond = async () => ({ organization_id: 'org-1', items })
    const data = await settle()
    expect(calls).toEqual(['org-1'])
    // Plots and seasons: one organization-wide request, never one per farm.
    expect(listingCalls).toEqual(['org-1'])
    expect(perFarmCalls).toEqual([])
    expect(data.rows).toHaveLength(n)
    for (const row of data.rows) {
      const it = items.find((x) => x.crop_season_id === row.seasonId)!
      const view = carbonView({ readiness: it.readiness, result: it.actual, liveEfConfigVersion: 'v1',
        fixTarget: `/crop-seasons/${row.seasonId}`, resultTarget: `/crop-seasons/${row.seasonId}/carbon` })
      expect(row.error).toBeUndefined()
      expect(row.loading).toBe(false)
      expect(row.carbon).toBe(view.calculationStatus)
      expect(row.data).toBe(view.userFixableGaps.length ? 'missing' : 'complete')
      expect(row.totalCo2eKg).toBe(it.actual ? it.actual.total_co2e_kg : null)
    }
  })

  it('a season whose status failed is an error on that row only', async () => {
    const items = useSeasons(6)
    items[2] = { ...items[2], readiness: null, readiness_error: { code: 'internal_error', message: 'Lỗi hệ thống.' } }
    respond = async () => ({ organization_id: 'org-1', items })
    const data = await settle()
    const broken = data.rows.find((r) => r.seasonId === 's-2')!
    expect(broken.error).toBe('Lỗi hệ thống.')
    expect(broken.carbon).toBe('unknown')
    expect(data.rows.filter((r) => r.error)).toHaveLength(1)
  })

  it('a season the answer does not mention is not guessed', async () => {
    const items = useSeasons(3).filter((i) => i.crop_season_id !== 's-1')
    respond = async () => ({ organization_id: 'org-1', items })
    const data = await settle()
    const missing = data.rows.find((r) => r.seasonId === 's-1')!
    expect(missing.error).toBeTruthy()
    expect(missing.carbon).toBe('unknown')
    expect(data.rows.filter((r) => !r.error)).toHaveLength(2)
  })

  it('when the status request fails, every row says so instead of showing a state', async () => {
    useSeasons(4)
    respond = async () => { throw new Error('Không thể kết nối FastAPI.') }
    const data = await settle()
    expect(data.rows).toHaveLength(4)
    for (const row of data.rows) {
      expect(row.error).toBe('Không thể kết nối FastAPI.')
      expect(row.carbon).toBe('unknown')
    }
  })
})
