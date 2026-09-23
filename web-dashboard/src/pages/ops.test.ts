import { describe, expect, it } from 'vitest'
import type { CarbonMissingInput } from '../api/carbon'
import { exceptionsOf, type OpsRow } from './ops'

/* The management queue is a work list: only real, server-reported states get
 * in, worst first, each with the action that resolves it. */

const missing = (label: string): CarbonMissingInput => ({
  code: label, label, detail: 'd', flow: 'activity', activity_type: 'straw_management', blocking: true, records: [],
})
const limitation: CarbonMissingInput = {
  code: 'fuel_factor_unverified', label: 'Hệ số nhiên liệu chưa xác minh', detail: 'd',
  flow: 'factor_unavailable', activity_type: 'fuel', blocking: true, records: [],
}
const row = (over: Partial<OpsRow> = {}): OpsRow => ({
  seasonId: 's1', seasonName: 'DEMO-HT-2026', statusLabel: 'Đang canh tác',
  farmId: 'f1', farmName: 'Hộ demo 1', farmCode: 'DEMO-FARM-01',
  plotId: 'p1', plotName: 'Thửa demo 1.1', plotCode: 'DEMO-PLOT-01',
  missing: [], limitations: [], data: 'complete', carbon: 'calculated', view: null,
  carbonPerKg: 0.4, totalCo2eKg: null, calculatedAt: '2026-09-20T00:00:00Z', mrv: null, ...over,
})

describe('exception queue', () => {
  it('puts missing data above everything else and names the action', () => {
    const queue = exceptionsOf([
      row({ seasonId: 'ready', carbon: 'ready', data: 'complete' }),
      row({ seasonId: 'gap', missing: [missing('Thiếu số ngày vùi rơm')], data: 'missing', carbon: 'missing_data' }),
    ])
    expect(queue.map((e) => e.severity)).toEqual(['high', 'medium'])
    expect(queue[0]).toMatchObject({ id: 'gap:missing', action: { label: 'Xử lý', to: '/crop-seasons/gap' } })
    expect(queue[0].detail).toContain('Thiếu số ngày vùi rơm')
    expect(queue[1].action.label).toBe('Tính ngay')
  })

  it('reports an unverified factor as a low-severity limitation, never as a repair', () => {
    const queue = exceptionsOf([row({ carbon: 'methodology_limited', limitations: [limitation] })])
    expect(queue).toHaveLength(1)
    expect(queue[0]).toMatchObject({ severity: 'low', issue: 'Giới hạn của bộ hệ số' })
    expect(queue[0].action.label).toBe('Xem')
  })

  it('queues an MRV case that is still open, and leaves a finished one alone', () => {
    // `draft` and `in_progress` are open; `verified`/`closed` are settled.
    // The old filter compared against 'approved'/'exported', values that are
    // not in `mrv_case_status`, so every case queued for ever.
    const open = exceptionsOf([row({ mrv: { caseId: 'c1', caseCode: 'MRV-01', status: 'draft' } })])
    expect(open[0]).toMatchObject({ severity: 'medium', action: { label: 'Mở hồ sơ MRV', to: '/mrv' } })
    // No approve endpoint exists, so the queue never promises an approval.
    expect(open[0].action.label).not.toBe('Duyệt MRV')
    // …and it names the status in Vietnamese instead of leaking `draft`.
    expect(open[0].detail).toContain('Bản nháp')
    expect(open[0].detail).not.toContain('draft')
    expect(exceptionsOf([row({ mrv: { caseId: 'c1', caseCode: 'MRV-01', status: 'verified' } })])).toEqual([])
    expect(exceptionsOf([row({ mrv: { caseId: 'c1', caseCode: 'MRV-01', status: 'closed' } })])).toEqual([])
  })

  it('queues a stale Carbon result as something to recalculate', () => {
    const queue = exceptionsOf([row({ carbon: 'stale' })])
    expect(queue).toHaveLength(1)
    expect(queue[0]).toMatchObject({ issue: 'Kết quả Carbon đã cũ', action: { label: 'Tính lại' } })
  })

  it('keeps a season nothing is wrong with out of the queue', () => {
    expect(exceptionsOf([row()])).toEqual([])
  })

  it('surfaces a season whose data could not be read instead of dropping it', () => {
    const queue = exceptionsOf([row({ error: 'Không đọc được', missing: [missing('x')] })])
    expect(queue).toHaveLength(1)
    expect(queue[0].issue).toBe('Không đọc được dữ liệu vụ')
  })
})
