import type { Session } from '@supabase/supabase-js'
import { supabase } from '../utils/supabase'
import { apiRequest, beginIdentity, currentAccessToken, endSession, setAccessToken, setUnauthorizedHandler } from './client'
import { clearOrganizationCache } from './organizations'
import { clearViewerHint } from './me'
import { clearFarmerCache } from '../farmer/data'
import { clearQueryCache, setQueryUser } from '../query/client'

function requireAuthClient() { if (!supabase) throw new Error('Thiếu VITE_SUPABASE_URL hoặc VITE_SUPABASE_PUBLISHABLE_KEY.'); return supabase }

/** Why a signed-in session stopped: the person asked (and the server confirmed
 *  it, or not yet), another tab of this browser ended it, or the token ran out. */
export type AuthEndReason = 'signed_out' | 'signed_out_unconfirmed' | 'ended_elsewhere' | 'expired'
const ended = new Set<(reason: AuthEndReason) => void>()
/** The app shell listens here and drops to the login screen — no page has to
 * notice a dead session on its own and render a half-signed-in state. */
export function onAuthEnded(fn: (reason: AuthEndReason) => void): () => void {
  ended.add(fn)
  return () => { ended.delete(fn) }
}

const refreshed = new Set<() => void>()
/** Fires after the access token was refreshed (background refresh or a 401
 *  recovered by a refresh). The shell re-reads /v1/me then: the person's role
 *  may have changed while the tab stayed open. */
export function onSessionRefreshed(fn: () => void): () => void {
  refreshed.add(fn)
  return () => { refreshed.delete(fn) }
}
function notifyRefreshed() { for (const fn of refreshed) fn() }

const replaced = new Set<(session: Session) => void>()
/** Fires when Supabase reports a sign-in of a DIFFERENT user than this tab's
 *  (another tab of the same browser signed someone else in; the storage and
 *  the token are shared). The shell must re-verify with that session instead
 *  of showing the new person's data under the old person's role. */
export function onSessionReplaced(fn: (session: Session) => void): () => void {
  replaced.add(fn)
  return () => { replaced.delete(fn) }
}
let liveUserId: string | null = null

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
  clearQueryCache()
  clearViewerHint()
  if (!live) return
  live = false
  for (const fn of ended) fn(reason)
}

/** `session`, when it belongs to someone other than this tab's live person. */
function otherPerson(session: Session | null): Session | null {
  return session?.access_token && session.user?.id && live && liveUserId && session.user.id !== liveUserId ? session : null
}

/** Another tab signed a different person in (the storage and the token are
 *  shared). From here on nothing asked for the previous person may be sent or
 *  retried with the new token, and nothing cached for them may be shown. */
function replaceWith(session: Session) {
  beginIdentity()
  liveUserId = session.user.id
  setAccessToken(session.access_token)
  setQueryUser(session.user.id)   // clears the query cache on a change of user
  clearOrganizationCache()
  clearFarmerCache()
  clearViewerHint()
  for (const fn of replaced) fn(session)
}

/** Another tab of this browser removed the stored session (its sign-out, even
 *  one whose /logout never answered): this tab is signed out too. Without this,
 *  a second tab kept its Manager screen and in-memory session after the first
 *  tab had shown "signed out" (real Chrome, R3). auth-js's own cross-tab
 *  SIGNED_OUT only arrives once that /logout returns. */
function watchStoredSession(client: NonNullable<typeof supabase>) {
  const key = storageKeyOf(client)
  if (!key || typeof addEventListener !== 'function') return
  addEventListener('storage', (e: StorageEvent) => {
    if (e.key !== null && e.key !== key) return
    if (e.key === key && e.newValue !== null) return   // a refresh or another sign-in: not an ending
    if (!live) return
    finish('ended_elsewhere')
    // Drop auth-js's in-memory copy too; nothing is stored any more, so this
    // sends nothing, and its SIGNED_OUT finds the session already ended.
    void client.auth.signOut({ scope: 'local' }).catch(() => undefined)
  })
}

/** Supabase refreshes the token in the background; the API client has to be
 * told, or every request after the first hour goes out with a dead token. */
let watching = false
function watchSession() {
  if (watching || !supabase) return
  watching = true
  watchStoredSession(supabase)
  supabase.auth.onAuthStateChange((event, session) => {
    // Whatever the event is called: a SIGNED_IN from the other tab, or a
    // TOKEN_REFRESHED that picked up the other person's stored session.
    const other = otherPerson(session)
    if (other) { replaceWith(other); return }
    if (session?.access_token && (event === 'TOKEN_REFRESHED' || event === 'SIGNED_IN')) setAccessToken(session.access_token)
    if (session?.access_token && event === 'TOKEN_REFRESHED') notifyRefreshed()
    if (session?.user?.id && event === 'SIGNED_IN') setQueryUser(session.user.id)
    if (event === 'SIGNED_OUT' && !signingOut) finish('expired')
  })
}

// A 401 on a request that carried a token: try one refresh, else the session is over.
setUnauthorizedHandler(async () => {
  if (!supabase) return null
  try {
    const { data, error } = await supabase.auth.refreshSession()
    const session = error ? null : data.session
    // The refresh uses whatever session is stored, which another tab may have
    // replaced with someone else's: that is a replacement, never a token for
    // this request (the API client refuses it because the identity moved).
    const other = otherPerson(session)
    if (other) { replaceWith(other); return other.access_token }
    const token = session?.access_token ?? null
    if (token) { setAccessToken(token); notifyRefreshed(); return token }
  } catch { /* fall through: the session cannot be recovered */ }
  finish('expired')
  return null
})

export async function restoreSession(): Promise<Session | null> {
  const { data, error } = await requireAuthClient().auth.getSession()
  if (error) throw error
  setAccessToken(data.session?.access_token ?? null)
  setQueryUser(data.session?.user?.id ?? null)
  live = Boolean(data.session)
  liveUserId = data.session?.user?.id ?? null
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
  const client = requireAuthClient()
  // A sign-out still running would, when it returns, remove the session this
  // sign-in is about to store (auth-js removes whatever is stored by then) and
  // the next person would be dropped minutes later. It is bounded
  // (LOGOUT_TIMEOUT_MS), so waiting for it is too.
  if (pendingSignOut) await pendingSignOut
  const { data, error } = await client.auth.signInWithPassword({ email, password })
  if (error) throw new Error(signInErrorMessage(error))
  beginIdentity()
  unconfirmedToken = null
  setAccessToken(data.session?.access_token ?? null)
  setQueryUser(data.session?.user?.id ?? null)
  live = Boolean(data.session)
  liveUserId = data.session?.user?.id ?? null
  watchSession()
  return data.session
}

/** For a page that has already been told its session is gone: leave now. */
export function expireSession(): void { finish('expired') }

let signingOut = false
/** The server sign-out still running after the shell already left, if any. */
let pendingSignOut: Promise<unknown> | null = null
/** How long the shell waits for the server sign-out before leaving anyway. */
export const SIGN_OUT_WAIT_MS = 1500

function storageKeyOf(client: NonNullable<typeof supabase>): string | null {
  const key = (client.auth as unknown as { storageKey?: unknown }).storageKey
  return typeof key === 'string' && key ? key : null
}

/** Remove the stored Supabase session of this browser, without the network.
 *  auth-js only removes it once its /logout call returns; until then a reload
 *  (or the next person opening the site) would restore the session the person
 *  was just told had ended. Removing it also fires a `storage` event, which is
 *  how the other tabs of this browser learn of it (see watchStoredSession). */
function dropStoredSession(client: NonNullable<typeof supabase>) {
  const key = storageKeyOf(client)
  if (!key) return
  try { for (const k of [key, `${key}-user`, `${key}-code-verifier`]) localStorage.removeItem(k) } catch { /* storage unavailable */ }
}

/** True when this browser no longer stores a Supabase session. */
function storedSessionGone(client: NonNullable<typeof supabase>): boolean {
  const key = storageKeyOf(client)
  if (!key) return false
  try { return localStorage.getItem(key) === null } catch { return false }
}

/* ------------------------------------------------- server-side revocation */

/** The access token of a sign-out the server has not confirmed, kept in this
 *  tab's memory only so "Thử xác nhận lại" can ask again. Dropped on success
 *  and on the next sign-in. */
let unconfirmedToken: string | null = null
const revocationConfirmed = new Set<() => void>()
/** Fires when a sign-out first reported as unconfirmed is later confirmed by
 *  the server (the late answer arrived, or a retry succeeded). */
export function onSignOutConfirmed(fn: () => void): () => void {
  revocationConfirmed.add(fn)
  return () => { revocationConfirmed.delete(fn) }
}
function confirmRevocation(token: string) {
  if (unconfirmedToken !== token) return
  unconfirmedToken = null
  for (const fn of revocationConfirmed) fn()
}

/** Ask the server again to end every session of the account that signed out
 *  here (scope `global`). True only when the server confirmed it. False when
 *  there is nothing to confirm, the network still fails, or the token has
 *  already expired (the server can no longer be asked with it). */
export async function confirmSignOut(): Promise<boolean> {
  const token = unconfirmedToken
  if (!token || !supabase) return false
  try {
    const { error } = await supabase.auth.admin.signOut(token, 'global')
    if (error) return false
  } catch {
    return false
  }
  confirmRevocation(token)
  return true
}

/**
 * Sign out is a local decision first: the tab is cleared and the shell leaves
 * even when the server call fails (offline, or a token already expired), since
 * a failed network call must never leave someone stuck inside the app.
 *
 * Two separate facts decide what the login screen then says:
 *  - local: this browser no longer stores the session (always made true here);
 *  - server: Supabase confirmed the revocation (`/logout` answered). Only when
 *    both hold is it "Bạn đã đăng xuất". Otherwise the reason is
 *    `signed_out_unconfirmed`: signed out on this device, but the session may
 *    still be valid on the server, and the screen says so.
 */
export async function signOut() {
  signingOut = true
  const client = requireAuthClient()
  const token = currentAccessToken()
  // Revoke on the server, but never hold the person inside the app for it:
  // measured on a phone profile the round trip took over three seconds, and
  // the shell stayed on screen the whole time. Wait at most 1.5s, then leave.
  // auth-js answers { error } (it does not throw) when the network fails.
  const remote: Promise<boolean> = client.auth.signOut().then(({ error }) => !error, () => false)
  pendingSignOut = remote
  const outcome = await Promise.race([remote, new Promise<'pending'>((r) => setTimeout(() => r('pending'), SIGN_OUT_WAIT_MS))])
  // Not confirmed (yet): the stored session goes now anyway.
  if (outcome !== true) dropStoredSession(client)
  const confirmed = outcome === true && storedSessionGone(client)
  unconfirmedToken = confirmed ? null : token
  finish(confirmed ? 'signed_out' : 'signed_out_unconfirmed')
  void remote.then((ok) => { if (ok && token && outcome === 'pending' && storedSessionGone(client)) confirmRevocation(token) })
    .finally(() => {
      signingOut = false
      if (pendingSignOut === remote) pendingSignOut = null
    })
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
