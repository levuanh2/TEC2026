import { describe, expect, it } from 'vitest'
import type { Activity } from '../types'
import { harvestDate, sowingDate } from './seasonDates'

const act = (type: string, occurredAt: string): Activity =>
  ({ id: `${type}-${occurredAt}`, cropSeasonId: 's', occurredAt, type, detail: '', recorder: '', source: 'web' })

describe('season dates: planned, journal, or not recorded — never "chưa ghi" beside a journal entry', () => {
  it('uses the seeding activity when the journal has one', () => {
    const d = sowingDate({ plantingDate: undefined }, [act('seeding', '2026-06-02T08:00:00+07:00')])
    expect(d).toMatchObject({ value: '02/06/2026', source: 'journal', note: 'theo nhật ký' })
  })
  it('keeps the declared date visible (not overwritten) when it differs from the journal', () => {
    const d = sowingDate({ plantingDate: '2026-06-01' }, [act('seeding', '2026-06-03T08:00:00+07:00')])
    expect(d.value).toBe('03/06/2026')
    expect(d.note).toBe('theo nhật ký · khai báo 01/06/2026')
  })
  it('falls back to the declared planting date, then to "not recorded"', () => {
    expect(sowingDate({ plantingDate: '2026-06-01' }, [])).toMatchObject({ value: '01/06/2026', source: 'season' })
    expect(sowingDate({}, [])).toMatchObject({ value: null, source: 'none' })
  })
  it('harvest: end-of-season date, else journal, else expected (labelled planned)', () => {
    expect(harvestDate({ harvestDate: '2026-09-20' }, [])).toMatchObject({ value: '20/09/2026', note: 'ngày kết thúc vụ' })
    expect(harvestDate({}, [act('harvest', '2026-09-18T07:00:00+07:00')])).toMatchObject({ value: '18/09/2026', source: 'journal' })
    expect(harvestDate({ expectedHarvestDate: '2026-09-25' }, [])).toMatchObject({ value: '25/09/2026', source: 'planned', note: 'dự kiến' })
    expect(harvestDate({}, [])).toMatchObject({ value: null, source: 'none' })
  })
})
