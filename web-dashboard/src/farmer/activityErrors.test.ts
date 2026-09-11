import { describe, expect, it } from 'vitest'
import { ApiError } from '../api/client'
import { mapActivityError } from './activityErrors'

describe('mapActivityError', () => {
  it('maps normalized 404 to a scope-safe message', () => {
    expect(mapActivityError(new ApiError(404, 'not_found', 'Activity not found or outside your scope.')).message)
      .toBe('Không tìm thấy bản ghi hoặc bạn không còn quyền truy cập.')
  })
  it('maps idempotency conflict to a reload-and-retry message', () => {
    const r = mapActivityError(new ApiError(409, 'duplicate_event', 'Idempotency key was already used with different activity data.'))
    expect(r.message).toMatch(/tải lại/)
    expect(r.retryable).toBe(false)
  })
  it('maps validation_error without leaking raw Pydantic JSON', () => {
    const r = mapActivityError(new ApiError(422, 'validation_error', '[{"loc":["body","data","amount_kg"]}]'))
    expect(r.message).not.toMatch(/loc|body|amount_kg/)
  })
  it('maps a 5xx to a not-confirmed, retryable message', () => {
    const r = mapActivityError(new ApiError(500, 'request_failed', 'Internal Server Error'))
    expect(r.retryable).toBe(true)
    expect(r.message).toMatch(/chưa được xác nhận/)
  })
  it('maps an offline failure to a retryable message', () => {
    const r = mapActivityError(new ApiError(0, 'offline', 'Không thể kết nối FastAPI.'))
    expect(r.retryable).toBe(true)
  })
  it('maps unauthenticated to a re-login message that is not retryable inline', () => {
    const r = mapActivityError(new ApiError(401, 'unauthenticated', 'Missing bearer token'))
    expect(r.retryable).toBe(false)
    expect(r.message).toMatch(/đăng nhập/)
  })
  it('falls back for a non-ApiError throw', () => {
    const r = mapActivityError(new Error('network exploded'))
    expect(r.retryable).toBe(true)
  })
})
