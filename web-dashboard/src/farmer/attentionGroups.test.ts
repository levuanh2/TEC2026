import { describe, expect, it } from 'vitest'
import { buildAttention } from './activityView'
import type { CarbonMissingInput } from '../api/carbon'
import type { SeasonMetrics } from '../api/metrics'

/* The dashboard shows a cost warning and a Carbon state side by side. The domain
 * rule is that they are independent — money is never a Carbon input — so the
 * items must carry separate groups and separate CTAs, and the cost item must not
 * be worded as if it were holding Carbon back. */

const metrics = (over: Partial<SeasonMetrics> = {}): SeasonMetrics => ({
  yieldKg: 6000, waterM3: 4000, fertilizerKg: 100, totalCo2eKg: null,
  waterPerKg: 0.66, fertilizerPerKg: 0.016, co2ePerKg: null, costPerKg: null,
  completeness: { water: true, fertilizer: true, cost: true, carbon: true },
  ...over,
})

const missing = (over: Partial<CarbonMissingInput> = {}): CarbonMissingInput => ({
  code: 'pre_season_water_regime', label: 'Thiếu chế độ nước trước vụ',
  detail: 'Tình trạng ngập nước trước khi vào vụ ảnh hưởng trực tiếp tới CH₄.',
  flow: 'carbon_methodology', activity_type: null, blocking: true, ...over,
})

const byId = (items: ReturnType<typeof buildAttention>, id: string) => items.find((i) => i.id === id)

describe('attention grouping: cost and Carbon are independent metrics', () => {
  it('puts the cost item in the resource group and Carbon in its own', () => {
    const items = buildAttention(
      metrics({ completeness: { water: true, fertilizer: true, cost: false, carbon: false } }),
      [], [missing()],
    )
    expect(byId(items, 'cost')!.group).toBe('resource')
    expect(byId(items, 'carbon')!.group).toBe('carbon')
  })

  it('states on the cost item that cost does not affect Carbon', () => {
    const items = buildAttention(
      metrics({ completeness: { water: true, fertilizer: true, cost: false, carbon: true } }), [], null,
    )
    expect(byId(items, 'cost')!.body).toContain('không ảnh hưởng tới kết quả Carbon')
  })

  it('never mentions cost in the Carbon item', () => {
    const items = buildAttention(
      metrics({ completeness: { water: true, fertilizer: true, cost: false, carbon: false } }),
      [], [missing()],
    )
    const carbon = byId(items, 'carbon')!
    expect(`${carbon.title} ${carbon.body}`.toLowerCase()).not.toContain('chi phí')
  })
})

describe('CTAs point at the flow that can actually supply the input', () => {
  it('routes the cost CTA to the season journal, where costs are edited', () => {
    const items = buildAttention(
      metrics({ completeness: { water: true, fertilizer: true, cost: false, carbon: true } }), [], null,
    )
    const cta = byId(items, 'cost')!.link!
    expect(cta.label).toBe('Bổ sung chi phí')
    expect(cta.to('s1')).toBe('/farmer/crop-seasons/s1/journal')
  })

  it('routes the Carbon CTA to the season Carbon tab, where the methodology panel is', () => {
    const items = buildAttention(metrics(), [], [missing()])
    const cta = byId(items, 'carbon')!.link!
    expect(cta.label).toBe('Bổ sung dữ liệu Carbon')
    expect(cta.to('s1')).toBe('/farmer/crop-seasons/s1/carbon')
  })

  it('gives the cost data-task recommendation the same cost CTA', () => {
    const rec = { id: 'r1', type: 'data_task', status: 'generated', ruleCode: 'data.completeness.cost', title: 'Bổ sung chi phí vật tư', reason: 'thiếu chi phí' } as never
    const items = buildAttention(metrics(), [rec], null)
    expect(items[0].link!.to('s9')).toBe('/farmer/crop-seasons/s9/journal')
    expect(items[0].group).toBe('resource')
  })
})

describe('Carbon message uses the server-named missing input', () => {
  it('names the single missing input instead of a generic failure', () => {
    const items = buildAttention(metrics(), [], [missing()])
    expect(byId(items, 'carbon')!.title).toBe('Thiếu chế độ nước trước vụ')
    expect(byId(items, 'carbon')!.tone).toBe('warning')
  })

  it('summarises when several inputs are missing', () => {
    const items = buildAttention(metrics(), [], [
      missing(),
      missing({ code: 'cultivation_days', label: 'Thiếu số ngày canh tác' }),
    ])
    const carbon = byId(items, 'carbon')!
    expect(carbon.title).toBe('Thiếu 2 dữ liệu để tính Carbon')
    expect(carbon.body).toContain('Thiếu chế độ nước trước vụ')
    expect(carbon.body).toContain('Thiếu số ngày canh tác')
  })

  it('counts only what the farmer can supply, and names the factor limit apart', () => {
    // A verified factor the set does not have is blocking, but no data entry
    // fixes it: counting it as "missing data" sends the farmer looking for a
    // form that does not exist.
    const items = buildAttention(metrics(), [], [
      missing(),
      missing({ code: 'fuel_factor_unverified', label: 'Hệ số nhiên liệu chưa xác minh', detail: 'Bộ hệ số chưa có giá trị đã xác minh cho nhiên liệu.', flow: 'factor_unavailable', activity_type: 'fuel' }),
    ])
    expect(byId(items, 'carbon')!.title).toBe('Thiếu chế độ nước trước vụ')
    const limit = byId(items, 'carbon-limit')!
    expect(limit.tone).toBe('info')
    expect(limit.link).toBeUndefined() // nothing to fill in
    expect(limit.body).toContain('Không thể bổ sung bằng cách nhập dữ liệu.')
  })

  it('ignores non-blocking inputs when deciding the Carbon message', () => {
    // A missing yield costs the intensity, not the calculation — it must not be
    // presented as the reason Carbon is unavailable.
    const items = buildAttention(
      metrics({ completeness: { water: true, fertilizer: true, cost: true, carbon: true } }), [],
      [missing({ code: 'harvest_yield', label: 'Chưa ghi sản lượng', flow: 'activity', activity_type: 'harvest', blocking: false })],
    )
    expect(byId(items, 'carbon')).toBeUndefined()
  })

  it('falls back to a calm generic message when readiness is unavailable', () => {
    const items = buildAttention(
      metrics({ completeness: { water: true, fertilizer: true, cost: true, carbon: false } }), [], null,
    )
    const carbon = byId(items, 'carbon')!
    expect(carbon.tone).toBe('info')
    expect(carbon.title).toBe('Chưa có kết quả Carbon cho vụ này')
    // Must not claim the methodology is unavailable — it is published.
    expect(carbon.body).not.toContain('phương pháp tính sẵn sàng')
  })

  it('missing cost alone never produces a Carbon item', () => {
    const items = buildAttention(
      metrics({ completeness: { water: true, fertilizer: true, cost: false, carbon: true } }), [], [],
    )
    expect(byId(items, 'carbon')).toBeUndefined()
    expect(byId(items, 'cost')).toBeDefined()
  })
})
