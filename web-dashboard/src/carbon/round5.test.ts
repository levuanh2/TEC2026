import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CarbonReadiness, CarbonResult } from '../api/carbon'
import { carbonView, isResultStale } from './readiness'
import { carbonSourceLabel, cleanWarning, isSimulation, notCounted, resultKindLabel, resultScenario } from './presentation'

const ready = (over: Partial<CarbonReadiness> = {}): CarbonReadiness => ({
  can_calculate: true, blocking_count: 0, missing_inputs: [], input_hash: 'h-now', ef_config_version: 'v1', ...over,
})
const stored = (over: Partial<CarbonResult> = {}): CarbonResult => ({
  crop_season_id: 's1', total_co2e_kg: 5183.52, co2e_per_kg: 0.997, breakdown: [], warnings: [],
  calculated_at: '2026-09-28T07:00:00Z', ef_config_version: 'v1', input_hash: 'h-now',
  scenario: 'as_recorded', calculation_kind: 'actual', ...over,
})

describe('getCarbon — never "latest of any kind"', () => {
  afterEach(() => { vi.restoreAllMocks(); vi.resetModules() })

  it('asks for the actual result by name by default, and a scenario only when named', async () => {
    const calls: string[] = []
    vi.doMock('../api/client', () => ({ apiRequest: (path: string) => { calls.push(path); return Promise.resolve({}) } }))
    const { getCarbon } = await import('../api/carbon')
    await getCarbon('s1')
    await getCarbon('s1', 'continuous_flooding')
    expect(calls).toEqual([
      '/v1/crop-seasons/s1/carbon?scenario=as_recorded',
      '/v1/crop-seasons/s1/carbon?scenario=continuous_flooding',
    ])
  })
})

describe('staleness from the server fingerprint', () => {
  it('same fingerprint → current, even when an activity (e.g. a cost) was saved later', () => {
    expect(isResultStale({ readiness: ready(), result: stored(), latestInputAt: '2026-09-29T00:00:00Z' })).toBe(false)
    const view = carbonView({ readiness: ready(), result: stored(), latestInputAt: '2026-09-29T00:00:00Z' })
    expect(view.calculationStatus).toBe('calculated')
    expect(view.label).toBe('Đã tính')
  })

  it('different fingerprint → stale, whatever the timestamps say', () => {
    expect(isResultStale({ readiness: ready({ input_hash: 'h-new' }), result: stored() })).toBe(true)
    expect(carbonView({ readiness: ready({ input_hash: 'h-new' }), result: stored() }).calculationStatus).toBe('stale')
  })

  it('a recalculation that stores the current fingerprint clears stale', () => {
    const before = carbonView({ readiness: ready({ input_hash: 'h-new' }), result: stored() })
    const after = carbonView({ readiness: ready({ input_hash: 'h-new' }), result: stored({ input_hash: 'h-new' }) })
    expect(before.isStale).toBe(true)
    expect(after.isStale).toBe(false)
  })

  it('a factor set that moved on is still stale with a matching input fingerprint', () => {
    expect(isResultStale({ readiness: ready({ ef_config_version: 'v2' }), result: stored() })).toBe(true)
  })

  it('never shows "Đã tính" and "Chưa có bản tính" at once: one state per season', () => {
    const none = carbonView({ readiness: ready(), result: null })
    expect(none.calculationStatus).toBe('ready')
    expect(none.label).not.toBe('Đã tính')
  })

  it('falls back to timestamps only when the server sends no fingerprint', () => {
    const r = ready({ input_hash: null })
    expect(isResultStale({ readiness: r, result: stored(), latestInputAt: '2026-09-29T00:00:00Z' })).toBe(true)
  })
})

describe('result kind and labels', () => {
  it('names the actual result and labels simulations as simulations', () => {
    expect(resultKindLabel(stored())).toBe('Kết quả vận hành · theo dữ liệu đã ghi')
    expect(resultKindLabel(stored({ scenario: 'continuous_flooding', calculation_kind: 'scenario' })))
      .toBe('Kịch bản mô phỏng · Ngập liên tục')
    expect(isSimulation(stored({ scenario: 'awd', calculation_kind: 'scenario' }))).toBe(true)
  })

  it('reads the DB enum `actual` from an older server as the actual result', () => {
    const old = { scenario: 'actual' as never, water_regime_scenario: undefined, calculation_kind: undefined }
    expect(resultScenario(old)).toBe('as_recorded')
    expect(isSimulation(old)).toBe(false)
  })

  it('every engine source has a meaningful name; nothing falls back to a raw value', () => {
    const names = ['ch4_rice_cultivation', 'n2o_fertilizer_direct', 'straw_burning', 'fuel_diesel', 'fuel', 'undefined', '']
      .map((source) => carbonSourceLabel({ source, gas: 'ch4' }))
    for (const n of names) {
      expect(n).not.toMatch(/undefined|_|^$/)
    }
    expect(carbonSourceLabel({ source: 'ch4_rice_cultivation' })).toMatch(/methane/)
    expect(carbonSourceLabel({ source: 'n2o_fertilizer_direct' })).toMatch(/N₂O từ phân/)
  })
})

describe('categories without a numeric line are named, never shown as 0 kg', () => {
  it('lists fuel/pump and straw with a reason when only CH₄ and N₂O were computed', () => {
    const r = stored({
      breakdown: [
        { source: 'ch4_rice_cultivation', gas: 'ch4', co2e_kg: 4500, factors_used: { 'factors.ch4_rice.efc': 1.3, 'factors.ch4_rice.cfoa.straw_incorporated_gt_30d': 0.19 } },
        { source: 'n2o_fertilizer_direct', gas: 'n2o', co2e_kg: 683.52 },
      ],
    })
    const missing = notCounted(r)
    expect(missing.map((m) => m.key)).toEqual(['fuel', 'straw'])
    expect(missing.find((m) => m.key === 'straw')?.reason).toMatch(/đã được tính trong dòng methane/)
    for (const m of missing) expect(m.reason).not.toMatch(/\b0 kg\b/)
    // The numeric lines still add up to the total.
    expect(r.breakdown.reduce((a, b) => a + b.co2e_kg, 0)).toBeCloseTo(r.total_co2e_kg, 2)
  })
})

describe('engine warnings are readable', () => {
  it('drops the season UUID and file paths', () => {
    const w = "Vụ 'c9184ab5-45c2-4af2-88ce-10b598818cbc': có ghi nhận thuốc BVTV nhưng phát thải upstream không nằm trong ranh giới hệ thống MVP (docs/CARBON_METHOD.md — NOT_IMPLEMENTED)."
    const out = cleanWarning(w)
    expect(out).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/)
    expect(out).not.toMatch(/docs\//)
    expect(out.startsWith('Có ghi nhận thuốc BVTV')).toBe(true)
  })
})

describe('a simulation computed on older data is flagged, never compared as current', () => {
  it('older than the actual → outdated; same or newer → current', async () => {
    const { simulationOutdated } = await import('./presentation')
    expect(simulationOutdated({ calculated_at: '2026-09-29T07:31:00Z' }, { calculated_at: '2026-09-29T07:52:00Z' })).toBe(true)
    expect(simulationOutdated({ calculated_at: '2026-09-29T07:53:00Z' }, { calculated_at: '2026-09-29T07:52:00Z' })).toBe(false)
    expect(simulationOutdated({ calculated_at: undefined }, { calculated_at: '2026-09-29T07:52:00Z' })).toBe(false)
  })
})
