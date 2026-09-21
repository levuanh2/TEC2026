import { describe, expect, it } from 'vitest'
import {
  currentMrvStep, mrvAggregateStatus, mrvProgress, presentMrvAggregate,
  presentMrvCaseStatus, presentMrvStep,
} from './mrvPresentation'

const steps = (...statuses: string[]) =>
  statuses.map((status, i) => ({ status, stepNo: i + 1, name: `Bước ${i + 1}` }))

const SIX = (done: number, active = 0, blocked = 0) => steps(
  ...Array.from({ length: 6 }, (_, i) =>
    i < done ? 'completed' : i < done + active ? 'in_progress' : i < done + active + blocked ? 'blocked' : 'not_started'),
)

describe('step status', () => {
  it('maps the six steps to Vietnamese visual states', () => {
    expect(presentMrvStep('completed')).toEqual({ label: 'Hoàn thành', icon: 'check', tone: 'completed' })
    expect(presentMrvStep('in_progress')).toMatchObject({ label: 'Đang thực hiện', tone: 'in_progress' })
    expect(presentMrvStep('blocked')).toMatchObject({ label: 'Bị chặn', tone: 'blocked' })
  })
})

describe('case status is not step status', () => {
  it('names a draft case "Bản nháp", never "Chưa bắt đầu"', () => {
    // The exact defect: `draft` is a case status, missed the step table and
    // fell through to "Chưa bắt đầu" above steps that were already running.
    expect(presentMrvCaseStatus('draft').label).toBe('Bản nháp')
    expect(presentMrvCaseStatus('draft').label).not.toBe('Chưa bắt đầu')
  })

  it('covers every mrv_case_status value', () => {
    expect(presentMrvCaseStatus('in_progress').label).toBe('Đang thực hiện')
    expect(presentMrvCaseStatus('ready_for_verification').label).toBe('Chờ thẩm định')
    expect(presentMrvCaseStatus('verified').label).toBe('Đã thẩm định')
    expect(presentMrvCaseStatus('closed').label).toBe('Đã đóng hồ sơ')
  })

  it('never leaks a raw value for something unexpected', () => {
    expect(presentMrvCaseStatus('some_new_status').label).toBe('Chưa rõ')
  })
})

describe('aggregate status is derived from the six steps', () => {
  it('0/6 and nothing active → Chưa bắt đầu', () => {
    expect(mrvAggregateStatus(SIX(0))).toBe('not_started')
    expect(presentMrvAggregate(SIX(0)).label).toBe('Chưa bắt đầu')
  })

  it('a step in progress → Đang thực hiện', () => {
    expect(mrvAggregateStatus(SIX(0, 1))).toBe('in_progress')
    expect(presentMrvAggregate(SIX(0, 1)).label).toBe('Đang thực hiện')
  })

  it('the reported contradiction: 1/6 done with one active is never "Chưa bắt đầu"', () => {
    const agg = presentMrvAggregate(SIX(1, 1))
    expect(agg.status).toBe('in_progress')
    expect(agg.progress).toMatchObject({ done: 1, inProgress: 1, total: 6 })
    expect(agg.label).not.toBe('Chưa bắt đầu')
  })

  it('progress with nothing currently active is still Đang thực hiện', () => {
    expect(mrvAggregateStatus(SIX(3))).toBe('in_progress')
  })

  it('6/6 → Hoàn thành', () => {
    expect(mrvAggregateStatus(SIX(6))).toBe('completed')
    expect(presentMrvAggregate(SIX(6)).label).toBe('Hoàn thành')
  })

  it('a blocked step outranks everything else', () => {
    expect(mrvAggregateStatus(SIX(2, 1, 1))).toBe('blocked')
    expect(presentMrvAggregate(SIX(5, 0, 1)).label).toBe('Bị chặn')
  })

  it('no steps at all → Chưa bắt đầu, not a crash', () => {
    expect(mrvAggregateStatus([])).toBe('not_started')
  })
})

describe('progress counting', () => {
  it('counts done, in-progress and blocked against the total', () => {
    expect(mrvProgress(SIX(1, 1))).toEqual({ done: 1, inProgress: 1, blocked: 0, total: 6 })
  })
})

describe('current step', () => {
  it('points at the step under way', () => {
    expect(currentMrvStep(SIX(1, 1))?.stepNo).toBe(2)
  })
  it('falls back to the blocked step, then to the next unstarted one', () => {
    expect(currentMrvStep(steps('completed', 'blocked', 'not_started'))?.stepNo).toBe(2)
    expect(currentMrvStep(SIX(2))?.stepNo).toBe(3)
  })
  it('returns null when everything is done', () => {
    expect(currentMrvStep(SIX(6))).toBeNull()
  })
})
