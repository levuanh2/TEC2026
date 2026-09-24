import { describe, expect, it } from 'vitest'
import type { SeasonMetrics } from '../api/metrics'
import {
  JUDGEMENT_WORDS, NO_BENCHMARK, gramsPerKg, homeSummary, journalLine, litresPerKg, metricDetails, metricGroups,
  seasonFacts, yieldContext, type MetricDetail,
} from './metricsView'

const metrics = (over: Partial<SeasonMetrics> = {}): SeasonMetrics => ({
  yieldKg: 5200, waterM3: 330, fertilizerKg: 150, totalCo2eKg: null,
  waterPerKg: 330 / 5200, fertilizerPerKg: 150 / 5200, co2ePerKg: null, costPerKg: null,
  completeness: { water: true, fertilizer: true, cost: false, carbon: false },
  ...over,
})
const act = (type: string, payload: Record<string, unknown>) => ({ type, detail: JSON.stringify(payload) })
const noFacts = seasonFacts([], null)
const detail = (list: MetricDetail[], key: MetricDetail['key']) => list.find((d) => d.key === key)!
/** Every word a row can put on screen. */
const words = (d: MetricDetail) => [d.name, d.meaning, d.basis, d.status.text, d.missing, d.comparison, d.action?.label, ...d.method,
  d.primary?.value, d.primary?.unit, ...d.secondary.flatMap((r) => [r.value, r.unit])].filter(Boolean).join(' ')

describe('unit conversion is presentation only', () => {
  it('m³/kg becomes litres/kg on screen, and the server figure is still shown', () => {
    const m = metrics()
    const water = detail(metricDetails(m, noFacts), 'water')
    expect(water.primary).toEqual({ value: '63', unit: 'lít nước / kg lúa' })
    // The methodology unit keeps the server's own value.
    expect(water.secondary).toContainEqual({ value: '0,063', unit: 'm³ / kg lúa' })
    expect(litresPerKg(0.0635)).toBeCloseTo(63.5)
    expect(gramsPerKg(0.029)).toBeCloseTo(29)
  })

  it('never mutates the metric object it was handed', () => {
    const m = metrics({ costPerKg: 1200 })
    const before = JSON.stringify(m)
    metricDetails(m, seasonFacts([act('harvest', { yield_kg: 5200, harvested_area_ha: 1.2 })], 1.3))
    homeSummary(m, noFacts)
    expect(JSON.stringify(m)).toBe(before)
  })

  it('states the basis the reading was computed from', () => {
    const water = detail(metricDetails(metrics(), noFacts), 'water')
    expect(water.basis).toBe('Tính từ 330 m³ nước và 5.200 kg thóc đã ghi.')
    expect(water.action).toEqual({ label: 'Xem hoạt động tưới', to: '/farmer/journal?loai=irrigation' })
  })
})

describe('no grade without a benchmark', () => {
  it('every metric says there is no benchmark and uses no judgement word', () => {
    const facts = seasonFacts([act('fertilizer', { amount_kg: 150, total_cost_vnd: 900000 })], 1.3)
    const all = metricDetails(metrics({ totalCo2eKg: 5400, co2ePerKg: 1.04, costPerKg: 173 }), facts, {
      fixable: [], limitations: [], result: { breakdown: [{ source: 'ch4_rice_cultivation', co2e_kg: 5000 }], calculated_at: '2026-09-20T02:00:00Z', total_co2e_kg: 5400, co2e_per_kg: 1.04 }, stale: false, fixTo: '/farmer/carbon',
    })
    for (const d of all) {
      expect(d.comparison).toMatch(/Chưa có mốc/)
      const text = words(d).toLowerCase()
      for (const w of JUDGEMENT_WORDS) expect(text, `${d.key}: "${w}"`).not.toContain(w)
    }
    expect(detail(all, 'water').comparison).toBe(NO_BENCHMARK)
  })
})

describe('missing is never 0', () => {
  it('no yield → no reading, and the row names what to record', () => {
    const all = metricDetails(metrics({ yieldKg: null, waterPerKg: null, fertilizerPerKg: null }), noFacts)
    for (const d of all) {
      if (d.primary) expect(d.primary.value).not.toBe('0')
    }
    const water = detail(all, 'water')
    expect(water.primary).toBeNull()
    expect(water.missing).toMatch(/sản lượng/)
    expect(water.action).toEqual({ label: 'Ghi thu hoạch', create: 'harvest' })
  })

  it('cost with nothing recorded says so instead of 0 ₫/kg', () => {
    const cost = detail(metricDetails(metrics({ completeness: { water: true, fertilizer: true, cost: true, carbon: false } }), noFacts), 'cost')
    expect(cost.primary).toBeNull()
    expect(cost.status.text).toBe('Chưa đủ dữ liệu chi phí')
    expect(words(cost)).not.toMatch(/(^|\s)0 ₫/)
    expect(cost.action).toEqual({ label: 'Bổ sung chi phí trong Nhật ký', to: '/farmer/journal' })
  })

  it('cost partly recorded: shows what was recorded as partial, never as the total', () => {
    const facts = seasonFacts([act('fertilizer', { amount_kg: 50, total_cost_vnd: 400000 }), act('fuel', { liters: 15 })], null)
    const cost = detail(metricDetails(metrics(), facts), 'cost')
    expect(cost.primary).toBeNull()
    expect(cost.missing).toBe('1 hoạt động chưa ghi chi phí.')
    expect(cost.secondary[0].unit).toMatch(/chưa phải tổng/)
    expect(facts.costCategories.map((c) => [c.label, c.withCost, c.records])).toEqual([['Phân bón', 1, 1], ['Nhiên liệu', 0, 1]])
  })

  it('cost complete: total is the sum of recorded costs and ₫/kg is the server figure', () => {
    const facts = seasonFacts([act('fertilizer', { total_cost_vnd: 600000 }), act('seeding', { cost_vnd: 300000 })], null)
    const cost = detail(metricDetails(metrics({ costPerKg: 900000 / 5200, completeness: { water: true, fertilizer: true, cost: true, carbon: false } }), facts), 'cost')
    expect(cost.primary).toEqual({ value: '900.000', unit: '₫ đã ghi' })
    expect(cost.secondary).toContainEqual({ value: '173', unit: '₫ / kg lúa' })
    expect(cost.meaning).toMatch(/không phải tổng chi phí sản xuất/)
  })

  it('Carbon without a result shows no number, only what is missing and one fix action', () => {
    const carbon = detail(metricDetails(metrics(), noFacts, {
      fixable: [{ code: 'a', label: 'Thiếu A', detail: '', flow: 'activity', activity_type: 'straw_management', blocking: true }, { code: 'b', label: 'Thiếu B', detail: '', flow: 'activity', activity_type: 'straw_management', blocking: true }],
      limitations: [{ code: 'f', label: 'Hệ số nhiên liệu', detail: '', flow: 'factor_unavailable', activity_type: 'fuel', blocking: true }],
      result: null, stale: false, fixTo: '/farmer/carbon',
    }), 'carbon')
    expect(carbon.primary).toBeNull()
    expect(carbon.secondary).toEqual([])
    expect(carbon.missing).toBe('Còn thiếu 2 thông tin để tính Carbon.')
    expect(carbon.action).toEqual({ label: 'Bổ sung 2 thông tin', to: '/farmer/carbon' })
    // The factor limitation is named apart from what the farmer can fix.
    expect(carbon.method.join(' ')).toMatch(/Giới hạn phương pháp \(không phải do bạn nhập thiếu\): Hệ số nhiên liệu/)
  })
})

describe('Carbon, when calculated, reads in the agreed order', () => {
  it('total → per kg → top source → time → state', () => {
    const carbon = detail(metricDetails(metrics({ totalCo2eKg: 5400, co2ePerKg: 1.038 }), noFacts, {
      fixable: [], limitations: [],
      result: { breakdown: [{ source: 'n2o_fertilizer_direct', co2e_kg: 400 }, { source: 'ch4_rice_cultivation', co2e_kg: 5000 }], calculated_at: '2026-09-20T02:00:00Z', total_co2e_kg: 5400, co2e_per_kg: 1.038 },
      stale: true, fixTo: '/farmer/carbon',
    }), 'carbon')
    expect(carbon.primary).toEqual({ value: '5,4', unit: 't CO₂e cả vụ' })
    expect(carbon.secondary[0]).toEqual({ value: '1,038', unit: 'kg CO₂e / kg lúa' })
    expect(carbon.basis).toMatch(/^Nguồn đóng góp nhiều nhất: Khí mê-tan từ ruộng lúa\. Tính lúc /)
    expect(carbon.status).toEqual({ ok: false, text: 'Cần tính lại — dữ liệu đã đổi sau lần tính' })
  })
})

describe('semantic groups', () => {
  it('cost and Carbon never share a group, and cost is not a Carbon input', () => {
    const groups = metricGroups(metrics(), noFacts)
    expect(groups.map((g) => g.key)).toEqual(['resource', 'cost', 'carbon'])
    expect(groups[0].items.map((i) => i.key)).toEqual(['water', 'fertilizer'])
    expect(groups[1].items.map((i) => i.key)).toEqual(['cost'])
    expect(groups[2].items.map((i) => i.key)).toEqual(['carbon'])
    expect(groups[1].description).toContain('Không dùng để tính CO₂e')
    expect(detail(metricDetails(metrics(), noFacts), 'cost').group).not.toBe(detail(metricDetails(metrics(), noFacts), 'carbon').group)
  })
})

describe('fertiliser and yield context', () => {
  it('kg/ha leads when the area is known, and product mass is not called nutrient', () => {
    const facts = seasonFacts([act('harvest', { yield_kg: 5200, harvested_area_ha: 1.2 }), act('fertilizer', { amount_kg: 150, nitrogen_percent: 46 })], 1.3)
    const f = detail(metricDetails(metrics(), facts), 'fertilizer')
    expect(f.primary).toEqual({ value: '125', unit: 'kg phân / ha' })
    expect(f.secondary).toContainEqual({ value: '29', unit: 'g phân / kg lúa' })
    expect(f.method[0]).toMatch(/không phải lượng dưỡng chất N\/P\/K/)
    expect(f.action).toEqual({ label: 'Xem hoạt động bón phân', to: '/farmer/journal?loai=fertilizer' })
  })

  it('harvested area wins over plot area only when every harvest carries one', () => {
    expect(seasonFacts([act('harvest', { harvested_area_ha: 1.2 })], 1.3)).toMatchObject({ areaHa: 1.2, areaSource: 'harvested' })
    expect(seasonFacts([act('harvest', { harvested_area_ha: 1.2 }), act('harvest', {})], 1.3)).toMatchObject({ areaHa: 1.3, areaSource: 'plot' })
    expect(seasonFacts([], null)).toMatchObject({ areaHa: null, areaSource: null })
  })

  it('yield per ha names the missing field', () => {
    expect(yieldContext(metrics(), seasonFacts([], 1.3)).tonnesPerHa).toBe('4')
    expect(yieldContext(metrics({ yieldKg: null }), seasonFacts([], null)).missing).toBe('Chưa tính được năng suất: thiếu sản lượng thóc (hoạt động Thu hoạch) và diện tích thửa hoặc diện tích thu hoạch.')
  })
})

describe('Home', () => {
  it('the activity count is a journal line, not a KPI', () => {
    expect(journalLine(9)).toBe('Nhật ký: 9 hoạt động đã ghi')
    expect(journalLine(0)).toBe('Nhật ký: chưa có hoạt động nào')
    expect(homeSummary(metrics(), noFacts).map((s) => s.key)).toEqual(['water', 'fertilizer'])
  })
})

describe('presentation math (Round 4.3 gate)', () => {
  // The QA season: 5.200 kg thóc, 330 m³, 150 kg phân, harvested 1,2 ha on a 1,3 ha plot.
  const real = metrics({ waterPerKg: 0.063 })
  const facts = seasonFacts([act('harvest', { yield_kg: 5200, harvested_area_ha: 1.2 }), act('fertilizer', { amount_kg: 150 })], 1.3)

  it('0,063 m³/kg = 63 lít/kg', () => {
    expect(detail(metricDetails(real, facts), 'water').primary).toEqual({ value: '63', unit: 'lít nước / kg lúa' })
  })

  it('150 kg / 1,2 ha = 125 kg/ha — on the harvested area, not the 1,3 ha plot', () => {
    const f = detail(metricDetails(real, facts), 'fertilizer')
    expect(f.primary).toEqual({ value: '125', unit: 'kg phân / ha' })
    expect(150 / 1.3).not.toBeCloseTo(125) // the plot area would have given 115
    expect(f.basis).toContain('1,2 ha diện tích thu hoạch đã ghi')
    expect(f.method).toContain('kg/ha dùng diện tích thu hoạch đã ghi: 1,2 ha.')
  })

  it('5.200 kg / 1,2 ha ≈ 4,3 tấn/ha, labelled with the harvested area', () => {
    const y = yieldContext(real, facts)
    expect(y.tonnesPerHa).toBe('4,3')
    expect(y.areaHa).toBe(1.2)
    expect(y.areaLabel).toBe('Diện tích thu hoạch')
  })

  it('the UI sentence says product mass, not N/P/K, and names the denominator', () => {
    const f = detail(metricDetails(real, facts), 'fertilizer')
    expect(f.meaning).toBe('Khối lượng sản phẩm phân bón (không phải lượng N/P/K) đã ghi trên mỗi ha diện tích thu hoạch đã ghi — dùng để so với liều bón bạn dự định.')
  })

  it('never feeds a rounded figure into the next step', () => {
    // 100 kg on 0,3333 ha = 300,03 kg/ha → "300". Had the area been rounded to
    // 0,33 first, the result would be 303.
    const f = detail(metricDetails(metrics({ fertilizerKg: 100 }), seasonFacts([act('harvest', { harvested_area_ha: 0.3333 })], null)), 'fertilizer')
    expect(f.primary?.value).toBe('300')
    // 330 m³ on 1,2 ha = 275 m³/ha from the raw total, not from the rounded 63 l/kg.
    expect(detail(metricDetails(real, facts), 'water').secondary).toContainEqual({ value: '275', unit: 'm³ / ha' })
  })

  it('the server metric object is returned untouched', () => {
    const before = structuredClone(real)
    metricDetails(real, facts)
    yieldContext(real, facts)
    expect(real).toEqual(before)
  })
})
