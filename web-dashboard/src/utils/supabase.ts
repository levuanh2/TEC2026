import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

/** Longest a server sign-out may run. auth-js holds its lock for the whole
 *  call and, whenever the call finally returns, removes the session that is
 *  stored *then* -- by that time possibly the next person's. A bounded call
 *  ends (as a network error, after which auth-js still drops the local
 *  session) before anyone can be signed in behind it for long. */
export const LOGOUT_TIMEOUT_MS = 8_000

const isLogout = (input: RequestInfo | URL): boolean => {
  const href = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  return /\/auth\/v1\/logout(?:[?#]|$)/.test(href)
}

/** The fetch auth-js uses: unchanged, except that a sign-out request is
 *  aborted after LOGOUT_TIMEOUT_MS. `base` is resolved per call so tests can
 *  stub the global fetch. */
export function boundedAuthFetch(base: typeof fetch = (...a) => fetch(...a)): typeof fetch {
  return (input, init) => {
    if (!isLogout(input)) return base(input, init)
    const controller = new AbortController()
    const outer = init?.signal
    if (outer?.aborted) controller.abort(outer.reason)
    else outer?.addEventListener('abort', () => controller.abort(outer.reason), { once: true })
    const timer = setTimeout(() => controller.abort(new DOMException('sign-out timed out', 'TimeoutError')), LOGOUT_TIMEOUT_MS)
    return base(input, { ...init, signal: controller.signal }).finally(() => clearTimeout(timer))
  }
}

/** End every session of the account that owns `token` (scope `global`): the
 *  same `POST /auth/v1/logout` auth-js's signOut sends, with the person's OWN
 *  access token and the publishable key. It is NOT an admin call, and nothing
 *  here holds a service-role key. True only on a 2xx answer. */
export function revokerFor(baseUrl: string | undefined, key: string | undefined, fetchImpl: typeof fetch = boundedAuthFetch()) {
  return async (token: string): Promise<boolean> => {
    if (!baseUrl || !key || !token) return false
    try {
      const res = await fetchImpl(`${baseUrl.replace(/\/$/, '')}/auth/v1/logout?scope=global`, {
        method: 'POST',
        headers: { apikey: key, Authorization: `Bearer ${token}` },
      })
      return res.ok
    } catch {
      return false
    }
  }
}
export const revokeSessionsWithToken = revokerFor(url, publishableKey)

// Auth only. Dashboard data is intentionally fetched through FastAPI.
export const supabase = url && publishableKey ? createClient(url, publishableKey, { global: { fetch: boundedAuthFetch() } }) : null
