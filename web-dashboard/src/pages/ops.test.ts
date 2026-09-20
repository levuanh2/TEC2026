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
  seasonId: 's1', seasonName: 'DEMO-HT-2026', farmId: 'f1', farmName: 'Hộ demo 1', plotId: 'p1',
  missing: [], limitations: [], data: 'complete', carbon: 'calculated',
  carbonPerKg: 0.4, calculatedAt: '2026-09-20T00:00:00Z', mrv: null, ...over,
})

describe('exception queue', () => {
  it('puts missing data above everything else and names the action', () => {
    const queue = exceptionsOf([
      row({ seasonId: 'ready', carbon: 'ready', data: 'complete' }),
      row({ seasonId: 'gap', missing: [missing('Thiếu số ngày vùi rơm')], data: 'missing', carbon: 'blocked' }),
    ])
    expect(queue.map((e) => e.severity)).toEqual(['high', 'medium'])
    expect(queue[0]).toMatchObject({ id: 'gap:missing', action: { label: 'Xử lý', to: '/crop-seasons/gap' } })
    expect(queue[0].detail).toContain('Thiếu số ngày vùi rơm')
    expect(queue[1].action.label).toBe('Tính ngay')
  })

  it('reports an unverified factor as a low-severity limitation, never as a repair', () => {
    const queue = exceptionsOf([row({ carbon: 'limited', limitations: [limitation] })])
    expect(queue).toHaveLength(1)
    expect(queue[0]).toMatchObject({ severity: 'low', issue: 'Giới hạn của bộ hệ số' })
    expect(queue[0].action.label).toBe('Xem')
  })

  it('queues an MRV case that is still open, and leaves a finished one alone', () => {
    const open = exceptionsOf([row({ mrv: { caseId: 'c1', caseCode: 'MRV-01', status: 'in_review' } })])
    expect(open[0]).toMatchObject({ severity: 'medium', action: { label: 'Duyệt MRV', to: '/mrv' } })
    expect(exceptionsOf([row({ mrv: { caseId: 'c1', caseCode: 'MRV-01', status: 'approved' } })])).toEqual([])
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
