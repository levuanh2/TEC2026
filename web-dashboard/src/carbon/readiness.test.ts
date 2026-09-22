import { describe, expect, it } from 'vitest'
import type { CarbonMissingInput, CarbonReadiness } from '../api/carbon'
import { carbonView, dataCompletenessLabel, isResultStale } from './readiness'

const gap = (over: Partial<CarbonMissingInput> = {}): CarbonMissingInput => ({
  code: 'pre_season_water_regime',
  label: 'Thiếu chế độ nước trước vụ',
  detail: '…',
  flow: 'carbon_methodology',
  activity_type: null,
  blocking: true,
  ...over,
})

const fuelLimit = () => gap({
  code: 'fuel_factor_unverified',
  label: 'Vụ có ghi nhiên liệu nhưng chưa có hệ số đã xác minh',
  flow: 'factor_unavailable',
  activity_type: 'fuel',
})

const yieldGap = () => gap({
  code: 'harvest_yield', label: 'Chưa ghi sản lượng thu hoạch',
  flow: 'activity', activity_type: 'harvest', blocking: false,
})

const readiness = (missing: CarbonMissingInput[]): CarbonReadiness => ({
  missing_inputs: missing,
  blocking_count: missing.filter((m) => m.blocking).length,
  can_calculate: missing.every((m) => !m.blocking),
})

const result = (calculated_at = '2026-09-10T02:00:00Z', ef_config_version = '0.3.0') =>
  ({ calculated_at, ef_config_version })

describe('carbonView — the five states', () => {
  it('1. user-fixable gaps → missing_data, and the action is a form', () => {
    const v = carbonView({ readiness: readiness([gap()]), fixTarget: '/farmer/carbon' })
    expect(v.calculationStatus).toBe('missing_data')
    expect(v.label).toBe('Thiếu dữ liệu')
    expect(v.userFixableGaps).toHaveLength(1)
    expect(v.methodologyLimitations).toHaveLength(0)
    expect(v.isReady).toBe(false)
    expect(v.nextAction).toMatchObject({ kind: 'fix_data', enabled: true })
    expect(v.nextActionTarget).toBe('/farmer/carbon')
  })

  it('2. only a factor limitation → methodology_limited, and NO repair action', () => {
    const v = carbonView({ readiness: readiness([fuelLimit()]), fixTarget: '/farmer/carbon' })
    expect(v.calculationStatus).toBe('methodology_limited')
    expect(v.label).toBe('Giới hạn hệ số')
    expect(v.userFixableGaps).toHaveLength(0)
    expect(v.methodologyLimitations).toHaveLength(1)
    expect(v.isReady).toBe(false)
    // The rule that broke trust: never offer a form that cannot fix this.
    expect(v.nextAction.kind).toBe('none')
    expect(v.nextActionTarget).toBeNull()
    expect(v.detail).toContain('Không thể bổ sung')
  })

  it('3. nothing blocking and no result → ready, calculation offered', () => {
    const v = carbonView({ readiness: readiness([]), resultTarget: '/carbon' })
    expect(v.calculationStatus).toBe('ready')
    expect(v.isReady).toBe(true)
    expect(v.nextAction).toMatchObject({ kind: 'calculate', enabled: true })
  })

  it('4. a stored result with fresh inputs → calculated', () => {
    const v = carbonView({ readiness: readiness([]), result: result(), resultTarget: '/carbon' })
    expect(v.calculationStatus).toBe('calculated')
    expect(v.isStale).toBe(false)
    expect(v.nextAction.kind).toBe('view_result')
  })

  it('5. inputs recorded after the calculation → stale, recalculation offered', () => {
    const v = carbonView({
      readiness: readiness([]),
      result: result('2026-09-10T02:00:00Z'),
      latestInputAt: '2026-09-12T06:00:00Z',
      resultTarget: '/carbon',
    })
    expect(v.calculationStatus).toBe('stale')
    expect(v.isStale).toBe(true)
    expect(v.label).toBe('Cần tính lại')
    expect(v.nextAction).toMatchObject({ kind: 'calculate', enabled: true })
  })

  it('readiness not loaded → unknown, never a guess', () => {
    const v = carbonView({ readiness: null })
    expect(v.calculationStatus).toBe('unknown')
    expect(v.isReady).toBe(false)
    expect(v.nextAction.kind).toBe('none')
  })
})

describe('precedence — every combination resolves to exactly one state', () => {
  const cases: Array<{ name: string; missing: CarbonMissingInput[]; res?: ReturnType<typeof result>; latest?: string; expect: string }> = [
    { name: 'fixable + limitation', missing: [gap(), fuelLimit()], expect: 'missing_data' },
    { name: 'fixable + result', missing: [gap()], res: result(), expect: 'missing_data' },
    { name: 'fixable + limitation + result', missing: [gap(), fuelLimit()], res: result(), expect: 'missing_data' },
    { name: 'limitation + result', missing: [fuelLimit()], res: result(), expect: 'methodology_limited' },
    { name: 'limitation + stale result', missing: [fuelLimit()], res: result(), latest: '2026-09-30T00:00:00Z', expect: 'methodology_limited' },
    { name: 'clean + stale result', missing: [], res: result(), latest: '2026-09-30T00:00:00Z', expect: 'stale' },
    { name: 'clean + result', missing: [], res: result(), expect: 'calculated' },
    { name: 'clean, no result', missing: [], expect: 'ready' },
    { name: 'optional gap only, no result', missing: [yieldGap()], expect: 'ready' },
    { name: 'optional gap + result', missing: [yieldGap()], res: result(), expect: 'calculated' },
    { name: 'fixable + optional gap', missing: [gap(), yieldGap()], expect: 'missing_data' },
    { name: 'limitation + optional gap', missing: [fuelLimit(), yieldGap()], expect: 'methodology_limited' },
  ]

  for (const c of cases) {
    it(`${c.name} → ${c.expect}`, () => {
      const v = carbonView({ readiness: readiness(c.missing), result: c.res ?? null, latestInputAt: c.latest ?? null })
      expect(v.calculationStatus).toBe(c.expect)
    })
  }
})

describe('the rules that keep the screens honest', () => {
  it('a factor limitation is never counted as data the user is missing', () => {
    const v = carbonView({ readiness: readiness([gap(), fuelLimit()]) })
    expect(v.userFixableGaps.map((m) => m.code)).toEqual(['pre_season_water_regime'])
    expect(v.methodologyLimitations.map((m) => m.code)).toEqual(['fuel_factor_unverified'])
    // The count a screen shows must be the fixable one, not both.
    expect(v.detail).toContain('Còn 1 thông tin')
  })

  it('never says "đủ dữ liệu" while a user-fixable gap remains', () => {
    expect(dataCompletenessLabel(carbonView({ readiness: readiness([gap()]) })).label)
      .toBe('Thiếu 1 thông tin')
  })

  it('says data is complete but names the limitation, instead of "đủ dữ liệu" alone', () => {
    const d = dataCompletenessLabel(carbonView({ readiness: readiness([fuelLimit()]) }))
    expect(d.label).toBe('Đủ dữ liệu · vướng hệ số')
    expect(d.tone).toBe('methodology')
  })

  it('never says "sẵn sàng tính" when a methodology limitation blocks the result', () => {
    // Even if a server ever reported can_calculate with a blocking limitation,
    // the client refuses to promise a calculation that cannot produce a number.
    const forced: CarbonReadiness = { missing_inputs: [fuelLimit()], blocking_count: 1, can_calculate: true }
    const v = carbonView({ readiness: forced })
    expect(v.isReady).toBe(false)
    expect(v.calculationStatus).toBe('methodology_limited')
    expect(v.label).not.toContain('Sẵn sàng')
  })

  it('never enables a calculate action that is certain to fail', () => {
    for (const missing of [[gap()], [fuelLimit()], [gap(), fuelLimit()]]) {
      const v = carbonView({ readiness: readiness(missing) })
      expect(v.nextAction.kind).not.toBe('calculate')
    }
  })

  it('an optional gap costs intensity only — it never blocks the calculation', () => {
    const v = carbonView({ readiness: readiness([yieldGap()]) })
    expect(v.isReady).toBe(true)
    expect(v.optionalGaps).toHaveLength(1)
    expect(v.userFixableGaps).toHaveLength(0)
  })
})

describe('isResultStale — only from facts on the wire', () => {
  it('no result is never stale', () => {
    expect(isResultStale({ readiness: null, result: null, latestInputAt: '2026-09-30T00:00:00Z' })).toBe(false)
  })

  it('an input older than the calculation is not stale', () => {
    expect(isResultStale({ readiness: null, result: result('2026-09-20T00:00:00Z'), latestInputAt: '2026-09-01T00:00:00Z' })).toBe(false)
  })

  it('a factor-set version that no longer matches the engine is stale', () => {
    expect(isResultStale({
      readiness: null,
      result: result('2026-09-20T00:00:00Z', '0.2.0-old'),
      liveEfConfigVersion: '0.3.0-ipcc2019-tier1-ar5',
    })).toBe(true)
  })

  it('the same factor-set version is not stale', () => {
    expect(isResultStale({
      readiness: null,
      result: result('2026-09-20T00:00:00Z', '0.3.0'),
      liveEfConfigVersion: '0.3.0',
    })).toBe(false)
  })

  it('without any change signal it refuses to claim staleness', () => {
    expect(isResultStale({ readiness: null, result: result() })).toBe(false)
  })

  it('an unparseable timestamp is not treated as a change', () => {
    expect(isResultStale({ readiness: null, result: result('not-a-date'), latestInputAt: '2026-09-30T00:00:00Z' })).toBe(false)
  })
})
