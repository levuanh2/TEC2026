import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiRequest, setAccessToken } from './client'

describe('FastAPI client', () => {
  afterEach(() => { vi.unstubAllGlobals(); setAccessToken(null) })
  it('passes the user JWT to FastAPI and parses a carbon response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ total_co2e_kg: 4, co2e_per_kg: null }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock); setAccessToken('user-jwt')
    const response = await apiRequest<{ total_co2e_kg: number; co2e_per_kg: number | null }>('/v1/crop-seasons/x/carbon')
    expect(response).toEqual({ total_co2e_kg: 4, co2e_per_kg: null })
    expect(fetchMock.mock.calls[0][1].headers.get('Authorization')).toBe('Bearer user-jwt')
  })
  it('maps a FastAPI carbon error without inventing a value', async () => {
    // Hợp đồng lỗi thống nhất: detail.error là object {code, message}, không phải string.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { error: { code: 'missing_emission_factor', message: 'GWP pending' } } }), { status: 422 })))
    await expect(apiRequest('/v1/carbon/calculate')).rejects.toMatchObject({ status: 422, code: 'missing_emission_factor', message: 'GWP pending' } satisfies Partial<ApiError>)
  })
  it('falls back safely if a legacy flat-string error body ever reaches the client', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { error: 'unexpected_shape' } }), { status: 500 })))
    await expect(apiRequest('/v1/carbon/calculate')).rejects.toMatchObject({ status: 500, code: 'request_failed' } satisfies Partial<ApiError>)
  })
  it('never forces Content-Type on a FormData body (multipart upload, e.g. CV image)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const form = new FormData()
    form.append('file', new Blob(['x'], { type: 'image/jpeg' }), 'leaf.jpg')
    await apiRequest('/v1/crop-seasons/x/cv/infer', { method: 'POST', body: form })
    expect(fetchMock.mock.calls[0][1].headers.has('Content-Type')).toBe(false)
  })
  it('still sets Content-Type: application/json for a plain JSON body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await apiRequest('/v1/recommendations/x', { method: 'PATCH', body: JSON.stringify({ status: 'accepted' }) })
    expect(fetchMock.mock.calls[0][1].headers.get('Content-Type')).toBe('application/json')
  })
})
