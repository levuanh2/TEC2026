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

export const OFFLINE_MESSAGE = 'Không thể kết nối FastAPI. Kiểm tra mạng hoặc API server.'
export const TIMEOUT_MESSAGE = 'Máy chủ phản hồi quá lâu nên yêu cầu đã dừng. Vui lòng thử lại.'

/** A read that has not answered by then is abandoned with a clear error
 * instead of leaving a page on a skeleton for a minute: production measured
 * 30 s and 61 s hangs when the backend could not reach its database. Writes
 * get no client timeout — abandoning one cannot tell the person whether it was
 * saved, and each write path already owns its retry/idempotency story. */
export const READ_TIMEOUT_MS = 30_000

/** Reads in flight at once. The API runs as one uvicorn worker on a small
 * EC2 instance, and the Management pages used to fire every read the moment
 * they mounted; concurrent heavy rollups were measured hitting the database's
 * 8 s statement timeout. Writes are never queued behind reads. */
export const MAX_CONCURRENT_READS = 4
let readsInFlight = 0
const readQueue: Array<() => void> = []

function abortError(signal?: AbortSignal | null): unknown {
  return signal?.reason ?? new DOMException('The operation was aborted.', 'AbortError')
}

/** Wait for a read slot; leaving the queue early if the caller aborts. */
function acquireRead(signal?: AbortSignal | null): Promise<() => void> {
  let released = false
  const release = () => {
    if (released) return
    released = true
    readsInFlight--
    readQueue.shift()?.()
  }
  if (signal?.aborted) return Promise.reject(abortError(signal))
  if (readsInFlight < MAX_CONCURRENT_READS) { readsInFlight++; return Promise.resolve(release) }
  return new Promise((resolve, reject) => {
    const start = () => { signal?.removeEventListener('abort', onAbort); readsInFlight++; resolve(release) }
    const onAbort = () => {
      const i = readQueue.indexOf(start)
      if (i >= 0) readQueue.splice(i, 1)
      reject(abortError(signal))
    }
    readQueue.push(start)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

/** Test hook: the limiter's live counters. */
export const readLimiterState = () => ({ inFlight: readsInFlight, queued: readQueue.length })

const isRead = (init: RequestInit) => !init.method || init.method.toUpperCase() === 'GET'

/** One fetch with the caller's abort signal and, for reads, a timeout. A
 * caller's abort is re-thrown as-is (the page left; nothing to show); a timeout
 * and a network failure become distinct ApiErrors the UI can explain. */
async function fetchOnce(url: string, init: RequestInit, headers: Headers): Promise<Response> {
  const outer = init.signal ?? null
  const controller = new AbortController()
  let timedOut = false
  const timer = isRead(init) ? setTimeout(() => { timedOut = true; controller.abort() }, READ_TIMEOUT_MS) : null
  const forward = () => controller.abort(outer?.reason)
  if (outer?.aborted) forward()
  else outer?.addEventListener('abort', forward, { once: true })
  try {
    return await fetch(url, { ...init, headers, signal: controller.signal })
  } catch {
    if (outer?.aborted) throw abortError(outer)
    if (timedOut) throw new ApiError(0, 'timeout', TIMEOUT_MESSAGE)
    throw new ApiError(0, 'offline', OFFLINE_MESSAGE)
  } finally {
    if (timer) clearTimeout(timer)
    outer?.removeEventListener('abort', forward)
  }
}

async function send(path: string, init: RequestInit, headers: Headers): Promise<Response> {
  if (sessionEnded) throw ended()
  const release = isRead(init) ? await acquireRead(init.signal) : null
  try {
    // The session may have ended while this read waited for a slot.
    if (sessionEnded) throw ended()
    const sentWith = accessToken
    if (sentWith) headers.set('Authorization', `Bearer ${sentWith}`)
    const response = await fetchOnce(`${baseUrl}${path}`, init, headers)
    if (response.status !== 401 || !sentWith || !onUnauthorized) return response
    // A token that was valid a moment ago: Supabase may simply have rotated it.
    const fresh = accessToken && accessToken !== sentWith ? accessToken : await onUnauthorized()
    if (!fresh) throw ended()
    headers.set('Authorization', `Bearer ${fresh}`)
    return await fetchOnce(`${baseUrl}${path}`, init, headers)
  } finally {
    release?.()
  }
}

/** Worth an automatic retry: the request never got an answer from a healthy
 * server (network down, or a gateway/upstream that said "try later"). Never a
 * 4xx — 401/403 are decisions, not hiccups — never a timeout (the server is
 * already struggling; piling on does not help) and never a plain 500, which is
 * a bug or a query that will fail the same way again. */
export function isTransientError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false
  if (error.status === 0) return error.code === 'offline'
  return error.status === 502 || error.status === 503 || error.status === 504
}

/** Told after every successful write, so cached reads it may have changed
 *  are marked stale in one place (registered by the query cache module) —
 *  no mutation call site can forget to refresh the screens that show it. */
let onWrite: (() => void) | null = null
export function setWriteListener(fn: (() => void) | null): void { onWrite = fn }

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
  if (!isRead(init)) onWrite?.()
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
