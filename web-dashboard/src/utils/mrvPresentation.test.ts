import { describe, expect, it } from 'vitest'
import { presentMrvStatus } from './mrvPresentation'

describe('MRV presentation', () => {
  it('maps backend status values to Vietnamese visual states', () => {
    expect(presentMrvStatus('completed')).toEqual({ label: 'Hoàn thành', icon: 'check', tone: 'completed' })
    expect(presentMrvStatus('in_progress')).toMatchObject({ label: 'Đang thực hiện', tone: 'in_progress' })
  })
})
