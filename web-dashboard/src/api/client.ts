export class ApiError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string) { super(message) }
}
const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
let accessToken: string | null = null
/** Set once a signed-in session has ended (sign-out or expiry). Every later
 * request fails here, before the network, until a new sign-in sets a token —
 * so a page still mounted behind the login screen cannot keep firing
 * authenticated reads with nothing to authenticate them. */
let sessionEnded = false
export const setAccessToken = (token: string | null) => { accessToken = token; if (token) sessionEnded = false }
export function endSession(): void { accessToken = null; sessionEnded = true }
export const SESSION_EXPIRED_MESSAGE = 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'

/** Called on a 401 for a request that carried a token. Returns a fresh token to
 * retry once with, or null when the session cannot be recovered. Registered by
 * the auth module so this file does not import Supabase. */
type UnauthorizedHandler = () => Promise<string | null>
let onUnauthorized: UnauthorizedHandler | null = null
export function setUnauthorizedHandler(fn: UnauthorizedHandler | null): void { onUnauthorized = fn }

function ended(): ApiError { return new ApiError(401, 'session_expired', SESSION_EXPIRED_MESSAGE) }

async function send(path: string, init: RequestInit, headers: Headers): Promise<Response> {
  if (sessionEnded) throw ended()
  const sentWith = accessToken
  if (sentWith) headers.set('Authorization', `Bearer ${sentWith}`)
  let response: Response
  try { response = await fetch(`${baseUrl}${path}`, { ...init, headers }) }
  catch { throw new ApiError(0, 'offline', 'Không thể kết nối FastAPI. Kiểm tra mạng hoặc API server.') }
  if (response.status !== 401 || !sentWith || !onUnauthorized) return response
  // A token that was valid a moment ago: Supabase may simply have rotated it.
  const fresh = accessToken && accessToken !== sentWith ? accessToken : await onUnauthorized()
  if (!fresh) throw ended()
  headers.set('Authorization', `Bearer ${fresh}`)
  try { response = await fetch(`${baseUrl}${path}`, { ...init, headers }) }
  catch { throw new ApiError(0, 'offline', 'Không thể kết nối FastAPI. Kiểm tra mạng hoặc API server.') }
  return response
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers); headers.set('Accept', 'application/json')
  // A FormData body (multipart upload) must NOT get a manual Content-Type —
  // the browser sets one itself with the correct boundary.
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await send(path, init, headers)
  const body = await response.json().catch(() => ({}))
  // Hợp đồng lỗi thống nhất backend (2026-09-08): { detail: { error: { code, message } } }
  // trên MỌI route, kể cả 422 tự động của Pydantic — không còn detail.error dạng string.
  if (!response.ok) { const detail = body.detail ?? body; const err = detail.error ?? {}; throw new ApiError(response.status, err.code ?? 'request_failed', err.message ?? 'Yêu cầu không thành công.') }
  return body as T
}

/** Same auth and error contract as `apiRequest`, but for binary downloads.
 *
 * Separate from `apiRequest` so the JSON path keeps one return type: an .xlsx
 * must never be run through `response.json()`. The error envelope is still
 * JSON, so a failure is parsed exactly as `apiRequest` parses it. */
export async function apiBlob(path: string, init: RequestInit = {}): Promise<Blob> {
  const headers = new Headers(init.headers)
  const response = await send(path, init, headers)
  if (!response.ok) {
    const body = await response.json().catch(() => ({} as any))
    const detail = body.detail ?? body
    const err = detail.error ?? {}
    throw new ApiError(response.status, err.code ?? 'request_failed', err.message ?? 'Yêu cầu không thành công.')
  }
  return response.blob()
}
