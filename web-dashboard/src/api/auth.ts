import type { Session } from '@supabase/supabase-js'
import { supabase } from '../utils/supabase'
import { apiRequest, endSession, setAccessToken, setUnauthorizedHandler } from './client'
import { clearOrganizationCache } from './organizations'
import { clearViewerHint } from './me'
import { clearFarmerCache } from '../farmer/data'

function requireAuthClient() { if (!supabase) throw new Error('Thiếu VITE_SUPABASE_URL hoặc VITE_SUPABASE_PUBLISHABLE_KEY.'); return supabase }

/** Why a signed-in session stopped: the person asked, or the token ran out. */
export type AuthEndReason = 'signed_out' | 'expired'
const ended = new Set<(reason: AuthEndReason) => void>()
/** The app shell listens here and drops to the login screen — no page has to
 * notice a dead session on its own and render a half-signed-in state. */
export function onAuthEnded(fn: (reason: AuthEndReason) => void): () => void {
  ended.add(fn)
  return () => { ended.delete(fn) }
}

/** True from a sign-in until that session ends. A failed refresh makes
 *  Supabase emit SIGNED_OUT *after* the 401 already ended the session; without
 *  this the shell heard "ended" twice, the second time while already on
 *  /login, and wrote `next=/login` over the page the person was on. */
let live = false
/** Drop every trace of the session in this tab, then tell the shell once. */
function finish(reason: AuthEndReason) {
  endSession()
  // The caches are session-scoped: this SPA reaches /login without a reload,
  // so anything left here would be shown to the next person who signs in.
  clearOrganizationCache()
  clearFarmerCache()
  clearViewerHint()
  if (!live) return
  live = false
  for (const fn of ended) fn(reason)
}

/** Supabase refreshes the token in the background; the API client has to be
 * told, or every request after the first hour goes out with a dead token. */
let watching = false
function watchSession() {
  if (watching || !supabase) return
  watching = true
  supabase.auth.onAuthStateChange((event, session) => {
    if (session?.access_token && (event === 'TOKEN_REFRESHED' || event === 'SIGNED_IN')) setAccessToken(session.access_token)
    if (event === 'SIGNED_OUT' && !signingOut) finish('expired')
  })
}

// A 401 on a request that carried a token: try one refresh, else the session is over.
setUnauthorizedHandler(async () => {
  if (!supabase) return null
  try {
    const { data, error } = await supabase.auth.refreshSession()
    const token = error ? null : data.session?.access_token ?? null
    if (token) { setAccessToken(token); return token }
  } catch { /* fall through: the session cannot be recovered */ }
  finish('expired')
  return null
})

export async function restoreSession(): Promise<Session | null> {
  const { data, error } = await requireAuthClient().auth.getSession()
  if (error) throw error
  setAccessToken(data.session?.access_token ?? null)
  live = Boolean(data.session)
  watchSession()
  return data.session
}

/** Supabase answers a failed sign-in in English; the login screen does not. */
export function signInErrorMessage(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error ?? '')
  if (/invalid login credentials|invalid.*(email|password)/i.test(raw)) return 'Email hoặc mật khẩu không đúng.'
  if (/email not confirmed/i.test(raw)) return 'Tài khoản chưa được xác nhận email.'
  if (/too many|rate limit/i.test(raw)) return 'Đăng nhập sai quá nhiều lần. Vui lòng thử lại sau ít phút.'
  if (/failed to fetch|network|load failed/i.test(raw)) return 'Không kết nối được máy chủ. Kiểm tra kết nối mạng rồi thử lại.'
  return 'Không thể đăng nhập. Vui lòng thử lại.'
}

export async function signIn(email: string, password: string) {
  const { data, error } = await requireAuthClient().auth.signInWithPassword({ email, password })
  if (error) throw new Error(signInErrorMessage(error))
  setAccessToken(data.session?.access_token ?? null)
  live = Boolean(data.session)
  watchSession()
  return data.session
}

/** For a page that has already been told its session is gone: leave now. */
export function expireSession(): void { finish('expired') }

let signingOut = false
/** Sign out is a local decision first: the tab is cleared and the shell leaves
 * even when the server call fails (offline, or a token already expired), since
 * a failed network call must never leave someone stuck inside the app. */
export async function signOut() {
  signingOut = true
  // Revoke on the server, but never hold the person inside the app for it:
  // measured on a phone profile the round trip took over three seconds, and
  // the shell stayed on screen the whole time. Wait at most 1.5s, then leave.
  const remote = requireAuthClient().auth.signOut().catch(() => undefined)
  await Promise.race([remote, new Promise((r) => setTimeout(r, 1500))])
  finish('signed_out')
  void remote.finally(() => { signingOut = false })
}

/** Supabase's password-change refusals, in the words the Account page uses. */
export function passwordChangeErrorMessage(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error ?? '')
  if (/should be different|same.*password/i.test(raw)) return 'Mật khẩu mới phải khác mật khẩu hiện tại.'
  if (/weak|at least|characters|password.*(short|length)/i.test(raw)) return 'Mật khẩu mới quá yếu. Dùng ít nhất 8 ký tự, có chữ hoa, chữ thường và số.'
  if (/reauthenticat|nonce/i.test(raw)) return 'Vui lòng đăng xuất, đăng nhập lại rồi đổi mật khẩu.'
  if (/failed to fetch|network|load failed/i.test(raw)) return 'Không kết nối được máy chủ. Kiểm tra kết nối mạng rồi thử lại.'
  return 'Chưa đổi được mật khẩu. Vui lòng thử lại.'
}

/**
 * Change the signed-in person's own password.
 *
 * The current password is checked first by signing in with it: that proves it
 * is the account holder at the keyboard (not an unlocked, unattended tab) and
 * gives a fresh session, which Supabase's secure password change requires.
 * This is the person's own Auth session -- nothing here holds or needs a
 * service-role credential.
 */
export async function changePassword(email: string, current: string, next: string): Promise<void> {
  const client = requireAuthClient()
  const { data, error } = await client.auth.signInWithPassword({ email, password: current })
  if (error) throw new Error(/invalid login credentials/i.test(error.message) ? 'Mật khẩu hiện tại không đúng.' : signInErrorMessage(error))
  setAccessToken(data.session?.access_token ?? null)
  const { error: updateError } = await client.auth.updateUser({ password: next })
  if (updateError) throw new Error(passwordChangeErrorMessage(updateError))
}

/** True while the account still has the temporary password its manager handed
 *  over. The flag is Supabase Auth `app_metadata` -- set and cleared only by the
 *  server; the browser can read it, never write it. Until it clears, FastAPI
 *  answers 403 `password_change_required` and the database returns nothing, so
 *  the shell shows only the change form. */
export function mustChangePassword(session: Session | null): boolean {
  return session?.user?.app_metadata?.must_change_password === true
}

/** Forced first login: the server checks the temporary password, sets the new
 *  one and clears the flag in one step (`POST /v1/me/password`). Changing the
 *  password revokes every refresh token of the account -- including any session
 *  opened with the temporary password -- so the new session comes from signing
 *  in with the new password, not from a refresh. */
export async function replaceTemporaryPassword(email: string, current: string, next: string): Promise<Session> {
  await apiRequest<{ must_change_password: boolean }>('/v1/me/password', {
    method: 'POST', body: JSON.stringify({ current_password: current, new_password: next }),
  })
  try {
    const session = await signIn(email, next)
    if (session) return session
  } catch { /* fall through: the change itself succeeded */ }
  throw new Error('Đã đổi mật khẩu. Vui lòng đăng nhập lại bằng mật khẩu mới.')
}
