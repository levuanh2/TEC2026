import { describe, expect, it } from 'vitest'
import type { CarbonMissingInput, CarbonReadiness } from '../api/carbon'
import type { Activity } from '../types'
import { nextAction } from './hybrid'

/* One primary action, and it has to be the RIGHT one: a farmer who opens the
 * app gets a single instruction, so the order these cases are checked in is
 * the product decision, not a detail. */

const issue = (over: Partial<CarbonMissingInput> = {}): CarbonMissingInput => ({
  code: 'straw_dry_matter', label: 'Thiếu tỷ lệ chất khô của rơm', detail: 'd',
  flow: 'activity', activity_type: 'straw_management', blocking: true, records: [], ...over,
})
const readiness = (...items: CarbonMissingInput[]): CarbonReadiness => ({
  can_calculate: !items.some((m) => m.blocking),
  blocking_count: items.filter((m) => m.blocking).length,
  missing_inputs: items,
})
const activity = (day: string): Activity => ({
  id: `a-${day}`, cropSeasonId: 's1', occurredAt: `${day}T02:00:00Z`, type: 'irrigation',
  detail: '{}', recorder: 'u', source: 'web',
})
const base = { hasSeason: true, canWrite: true, hasCarbonResult: false, today: '2026-09-21' }

describe('the one next action', () => {
  it('sends the farmer to the missing data first — Carbon cannot run without it', () => {
    const action = nextAction({ ...base, readiness: readiness(issue()), activities: [activity('2026-09-21')] })
    expect(action).toMatchObject({ kind: 'fix-data', cta: 'Bổ sung ngay' })
    expect(action!.body).toContain('1 thông tin')
  })

  it('never offers to fix an unverified factor — no data entry resolves it', () => {
    const fuel = issue({ code: 'fuel_factor_unverified', flow: 'factor_unavailable' })
    const action = nextAction({ ...base, readiness: readiness(fuel), activities: [] })
    expect(action?.kind).toBe('record') // today's work, not a fake repair
  })

  it('asks for today\'s record when nothing was written today', () => {
    const action = nextAction({ ...base, readiness: readiness(), activities: [activity('2026-09-20')] })
    expect(action).toMatchObject({ kind: 'record', cta: 'Ghi hoạt động' })
  })

  it('offers the calculation once the data is complete and today is recorded', () => {
    const action = nextAction({ ...base, readiness: readiness(), activities: [activity('2026-09-21')] })
    expect(action).toMatchObject({ kind: 'calculate', cta: 'Tính Carbon' })
  })

  it('points to the result when there is one and nothing outstanding', () => {
    const action = nextAction({ ...base, hasCarbonResult: true, readiness: readiness(), activities: [activity('2026-09-21')] })
    expect(action).toMatchObject({ kind: 'view-result', cta: 'Xem kết quả' })
  })

  it('gives a viewer no action at all', () => {
    expect(nextAction({ ...base, canWrite: false, readiness: readiness(issue()), activities: [] })).toBeNull()
    expect(nextAction({ ...base, hasSeason: false, readiness: readiness(), activities: [] })).toBeNull()
  })
})
