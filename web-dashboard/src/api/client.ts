export class ApiError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string) { super(message) }
}
const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
let accessToken: string | null = null
export const setAccessToken = (token: string | null) => { accessToken = token }
export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers); headers.set('Accept', 'application/json')
  // A FormData body (multipart upload) must NOT get a manual Content-Type —
  // the browser sets one itself with the correct boundary.
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  let response: Response
  try { response = await fetch(`${baseUrl}${path}`, { ...init, headers }) }
  catch { throw new ApiError(0, 'offline', 'Không thể kết nối FastAPI. Kiểm tra mạng hoặc API server.') }
  const body = await response.json().catch(() => ({}))
  // Hợp đồng lỗi thống nhất backend (2026-09-08): { detail: { error: { code, message } } }
  // trên MỌI route, kể cả 422 tự động của Pydantic — không còn detail.error dạng string.
  if (!response.ok) { const detail = body.detail ?? body; const err = detail.error ?? {}; throw new ApiError(response.status, err.code ?? 'request_failed', err.message ?? 'Yêu cầu không thành công.') }
  return body as T
}
