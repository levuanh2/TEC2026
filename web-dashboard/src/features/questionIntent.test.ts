import { describe, expect, it } from 'vitest'
import { foldVietnamese, suggestIntent } from './questionIntent'

describe('suggestIntent', () => {
  it.each([
    ['Vụ này còn thiếu dữ liệu gì?', 'data_gap'],
    ['Cần bổ sung gì để tính phát thải?', 'data_gap'],
    ['So với vụ trước của ruộng này thì sao?', 'compare'],
    ['Vụ này hơn hay kém vụ Đông Xuân?', 'compare'],
    ['Có tài liệu nào về tưới ngập khô xen kẽ?', 'evidence'],
    ['Quy trình AWD hướng dẫn thế nào?', 'evidence'],
    ['Vụ này đang thế nào?', 'explain'],
    ['Tóm tắt số liệu của vụ này', 'explain'],
    ['Phát thải vụ này là bao nhiêu?', 'explain'],
    ['Tôi nên làm gì để giảm phát thải?', 'recommend'],
    ['Làm thế nào để giảm khí mê-tan?', 'recommend'],
  ])('%s -> %s', (text, intent) => {
    expect(suggestIntent(text, true)).toEqual({ intent, actionNotAvailable: false })
  })

  it('never suggests an action to an audience that cannot request one', () => {
    expect(suggestIntent('Tôi nên làm gì để giảm phát thải?', false)).toEqual({ intent: null, actionNotAvailable: true })
  })

  it('"giới thiệu" is not a data gap', () => {
    expect(suggestIntent('Giới thiệu vụ này', true).intent).not.toBe('data_gap')
  })

  it('an unrecognised or empty question suggests nothing', () => {
    expect(suggestIntent('Xin chào', true)).toEqual({ intent: null, actionNotAvailable: false })
    expect(suggestIntent('   ', true)).toEqual({ intent: null, actionNotAvailable: false })
  })

  it('folds Vietnamese diacritics and đ', () => {
    expect(foldVietnamese('  Đồng   ruộng  ')).toBe('dong ruong')
  })
})
