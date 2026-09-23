import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiRequest, endSession, setAccessToken, setUnauthorizedHandler } from './client'

/* Round 4 P0.1 — a dead session must end the signed-in state, not leave pages
 * firing reads with a token nothing will accept. */

const ok = (body: unknown = {}) => new Response(JSON.stringify(body), { status: 200 })
const unauthorized = () => new Response(JSON.stringify({ detail: { error: { code: 'unauthenticated', message: 'Token expired' } } }), { status: 401 })

describe('session boundary in the API client', () => {
  afterEach(() => { vi.unstubAllGlobals(); setUnauthorizedHandler(null); setAccessToken(null) })

  it('refreshes once on a 401 and retries with the new token', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(unauthorized()).mockResolvedValueOnce(ok({ fine: true }))
    vi.stubGlobal('fetch', fetchMock)
    setAccessToken('old')
    const refresh = vi.fn().mockResolvedValue('new')
    setUnauthorizedHandler(refresh)
    await expect(apiRequest('/v1/farms')).resolves.toEqual({ fine: true })
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[1][1].headers.get('Authorization')).toBe('Bearer new')
  })

  it('ends with a Vietnamese session-expired error when the refresh fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(unauthorized()))
    setAccessToken('old')
    setUnauthorizedHandler(async () => { endSession(); return null })
    await expect(apiRequest('/v1/farms')).rejects.toMatchObject({ status: 401, code: 'session_expired', message: 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.' })
  })

  it('blocks every later authenticated request without touching the network', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    setAccessToken('t')
    endSession()
    await expect(apiRequest('/v1/farmer/scope')).rejects.toMatchObject({ code: 'session_expired' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('a new sign-in lifts the block', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ items: [] }))
    vi.stubGlobal('fetch', fetchMock)
    endSession()
    setAccessToken('fresh')
    await expect(apiRequest('/v1/farms')).resolves.toEqual({ items: [] })
    expect(fetchMock.mock.calls[0][1].headers.get('Authorization')).toBe('Bearer fresh')
  })

  it('does not try to refresh a request that carried no token', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(unauthorized()))
    const refresh = vi.fn()
    setUnauthorizedHandler(refresh)
    await expect(apiRequest('/v1/farms')).rejects.toMatchObject({ status: 401 })
    expect(refresh).not.toHaveBeenCalled()
  })
})
