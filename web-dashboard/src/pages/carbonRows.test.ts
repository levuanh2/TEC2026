import { describe, expect, it } from 'vitest'
import type { CarbonMissingInput } from '../api/carbon'
import { carbonIssue } from './operations'
import type { OpsRow } from './ops'

/* `/carbon` folds readiness, result, freshness and both totals into one
 * "Cần xử lý · Kết quả" cell. It must say what to fix while a season is
 * blocked and the server's own result once there is one — never an empty
 * column of dashes. */

const gap = (label: string): CarbonMissingInput => ({
  code: label, label, detail: 'd', flow: 'activity', activity_type: 'straw_management', blocking: true, records: [],
})
const row = (over: Partial<OpsRow> = {}): OpsRow => ({
  seasonId: 's1', seasonName: 'DEMO-HT-2026', statusLabel: 'Đang canh tác',
  farmId: 'f1', farmName: 'Hộ demo 1', plotId: 'p1', plotName: 'Thửa demo 1.1',
  missing: [], limitations: [], data: 'complete', carbon: 'calculated', view: null,
  carbonPerKg: null, totalCo2eKg: null, calculatedAt: null, mrv: null, ...over,
})

describe('carbonIssue', () => {
  it('names what is missing, without the repeated "Thiếu" prefix', () => {
    const out = carbonIssue(row({ carbon: 'missing_data', data: 'missing', missing: [gap('Thiếu số ngày canh tác'), gap('Thiếu tỷ lệ chất khô của rơm')] }))
    expect(out).toEqual({ head: 'Thiếu 2 thông tin', sub: 'số ngày canh tác, tỷ lệ chất khô của rơm' })
  })

  it('shows the stored result once there is one', () => {
    const out = carbonIssue(row({ carbon: 'calculated', totalCo2eKg: 1234.5, carbonPerKg: 0.42 }))
    expect(out.head).toBe('1.234,5 kg CO₂e')
    expect(out.sub).toBe('0,42 kg CO₂e / kg lúa')
  })

  it('keeps an old result visible but says it is old', () => {
    const out = carbonIssue(row({ carbon: 'stale', totalCo2eKg: 900 }))
    expect(out.head).toBe('Dữ liệu đã đổi sau lần tính')
    expect(out.sub).toBe('Kết quả cũ: 900 kg CO₂e')
  })

  it('reports a factor limitation as something data entry cannot fix', () => {
    const lim = { ...gap('Hệ số nhiên liệu chưa xác minh'), flow: 'factor_unavailable' as const }
    const out = carbonIssue(row({ carbon: 'methodology_limited', limitations: [lim] }))
    expect(out).toEqual({ head: 'Hệ số nhiên liệu chưa xác minh', sub: 'Nhập thêm dữ liệu không giải quyết được' })
  })

  it('never invents a figure for a season that is only ready', () => {
    expect(carbonIssue(row({ carbon: 'ready' }))).toEqual({ head: 'Đủ dữ liệu, chưa tính' })
  })
})
