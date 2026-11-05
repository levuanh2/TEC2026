import { Suspense, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { QueryClientProvider } from '@tanstack/react-query'
import { clearQueryData, queryClient } from './query/client'
import { mustChangePassword, onAuthEnded, onSessionRefreshed, onSessionReplaced, restoreSession, signIn, signOut, type AuthEndReason } from './api/auth'
import { clearViewerHint, getMe, readViewerHint, writeViewerHint, type CurrentUser } from './api/me'
import { ApiError } from './api/client'
import { clearOrganizationCache, getOrganization } from './api/organizations'
import { clearFarmerCache } from './farmer/data'
import { usingMockData } from './api/farms'
import { Ico } from './icons'
import { routeName, routeParam } from './routes'
import { buildNav } from './nav'
import { go, LoadingSkeleton, Notice, setLinkIntentHandler } from './ui'
import { prefetchRoute } from './routeChunks'
import { prefetchRouteData } from './query/prefetch'
import type { SeasonTab } from './pages/season'
import { OperationsOverview, SeasonsWorkspace } from './pages/operations'
import {
  FarmerAccountsPage, FarmerExperience, FarmPage, FarmsPage, MrvPage, OrganizationsPage,
  PerformancePage, PlotPage, ProvisionFarmerPage, SeasonHub,
} from './routeChunks'
import { AccountName, Sidebar } from './components/Sidebar'
import { useMobileDrawer } from './components/useMobileDrawer'
import { ForcedPasswordChange } from './components/ForcedPasswordChange'
import { prefetchFarmerScope } from './farmer/scope'

const ROLE_LABEL: Record<string, string> = {
  farmer: 'Nông hộ',
  cooperative_manager: 'Quản lý HTX',
  enterprise_viewer: 'Doanh nghiệp',
  regulator: 'Cơ quan quản lý',
}

/* --------------------------------------------------------------------- Login */

const ENDED_NOTICE: Record<AuthEndReason, { kind: 'info' | 'warning'; text: string }> = {
  signed_out: { kind: 'info', text: 'Bạn đã đăng xuất.' },
  expired: { kind: 'warning', text: 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.' },
}

function Login({ done, ended }: { done: (s: Session) => void; ended: AuthEndReason | null }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setBusy(true)
    setError('')
    const f = new FormData(e.currentTarget)
    try {
      const s = await signIn(String(f.get('email')), String(f.get('password')))
      if (s) {
        done(s)
      }
    } catch (x) {
      setError(x instanceof Error ? x.message : 'Không thể đăng nhập. Vui lòng thử lại.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <main className="login">
      <section className="login-card">
        <p className="eyebrow">AGRICARBON</p>
        <h1>Đăng nhập</h1>
        <p>Nhật ký canh tác, hiệu suất tài nguyên và Carbon cho lúa gạo.</p>
        {ended && !error && (
          <div role={ended === 'expired' ? 'alert' : 'status'} data-testid="auth-ended">
            <Notice kind={ENDED_NOTICE[ended].kind}>{ENDED_NOTICE[ended].text}</Notice>
          </div>
        )}
        <form onSubmit={submit}>
          <label>
            Email
            <input name="email" type="email" autoComplete="username" required />
          </label>
          <label>
            Mật khẩu
            <input name="password" type="password" autoComplete="current-password" required />
          </label>
          {error && <Notice kind="error">{error}</Notice>}
          <button className="btn" disabled={busy}>
            {busy ? 'Đang đăng nhập…' : ended === 'expired' ? 'Đăng nhập lại' : 'Đăng nhập'}
          </button>
        </form>
      </section>
    </main>
  )
}

/* ---------------------------------------------------------------- App shell */

function AppShell({ session, viewer, path, children }: { session: Session | null; viewer: CurrentUser; path: string; children: ReactNode }) {
  const drawer = useMobileDrawer(path)
  const [orgName, setOrgName] = useState<string | null>(null)
  /* "Chưa gán tổ chức" is a statement of fact about the account, so it must
   * not appear while the organisation's name is merely still being read —
   * which is what the audit saw for the first seconds of every load. The two
   * cases are now distinct: no organisation at all, versus one whose name has
   * not arrived yet. */
  const [orgLoading, setOrgLoading] = useState(Boolean(viewer.organizationId))

  useEffect(() => {
    if (!viewer.organizationId) {
      setOrgName(null)
      setOrgLoading(false)
      return
    }
    let alive = true
    setOrgLoading(true)
    void getOrganization(viewer.organizationId)
      .then((o) => alive && setOrgName(o.name))
      .catch(() => alive && setOrgName(null))
      .finally(() => { if (alive) setOrgLoading(false) })
    return () => {
      alive = false
    }
  }, [viewer.organizationId])

  // Hover/focus on any in-app link starts that route's code download and its
  // top-of-page organisation reads (both deduplicated against the cache).
  useEffect(() => {
    setLinkIntentHandler((to) => { prefetchRoute(to); prefetchRouteData(to, viewer.organizationId) })
    return () => setLinkIntentHandler(null)
  }, [viewer.organizationId])

  const groups = buildNav(viewer.role)
  const email = session?.user.email ?? 'Chế độ demo'

  return (
    <div className="shell">
      {/* First stop for a keyboard or screen-reader user: the sidebar is a
        * long list of links to walk past on every page. */}
      <a className="skip-link" href="#main">Bỏ qua điều hướng, tới nội dung chính</a>
      {/* Phones only: covers the workspace while the drawer is open, and a tap
        * on it closes the drawer. */}
      {drawer.open && <div className="shell-backdrop" data-testid="drawer-backdrop" aria-hidden="true" onClick={drawer.close} />}
      <Sidebar
        className={drawer.open ? 'is-open' : undefined}
        drawer={{ id: 'app-drawer', open: drawer.open, mobile: drawer.mobile, onClose: drawer.close, asideRef: drawer.drawerRef, closeRef: drawer.closeRef }}
        home="/dashboard"
        tagline="Hiệu suất tài nguyên · Carbon · MRV"
        navLabel="Điều hướng chính"
        groups={groups.map((g, gi) => ({
          key: g.label ?? String(gi),
          label: g.label,
          items: g.items.map((it) => ({
            to: it.to,
            label: it.label,
            icon: <Ico name={it.icon} size={15} />,
            current: path === it.to || (it.to !== '/dashboard' && path.startsWith(it.to)),
            onClick: drawer.close,
          })),
        }))}
        foot={<>
          <span className="avatar" aria-hidden="true">
            {email[0]?.toUpperCase()}
          </span>
          <span className="sidebar__id">
            <AccountName text={email} />
            <small>{ROLE_LABEL[viewer.role] ?? viewer.role}</small>
            {session && (
              <button className="link" onClick={() => void signOut()}>
                Đăng xuất
              </button>
            )}
          </span>
        </>}
      />

      <div className="main" inert={drawer.open ? true : undefined}>
        <header className="topbar">
          <div className="topbar__ctx">
            <button type="button" className="menu-btn" aria-label="Mở menu" aria-expanded={drawer.open} aria-controls="app-drawer" ref={drawer.openerRef} onClick={drawer.toggle}>
              <Ico name="menu" size={20} />
            </button>
            <span className="org-chip">
              {orgLoading
                ? <span className="skeleton" style={{ display: 'inline-block', width: 168, height: 13, borderRadius: 5 }} aria-label="Đang tải tổ chức" />
                : orgName ?? (viewer.organizationId ? 'Không đọc được tên tổ chức' : 'Chưa gán tổ chức')}
              {orgName && <small> · phạm vi hiện tại</small>}
            </span>
          </div>
          <span className="role-chip">{ROLE_LABEL[viewer.role] ?? viewer.role}</span>
        </header>
        <main className="content" id="main" tabIndex={-1}>
          {usingMockData && <Notice kind="warning">Dữ liệu minh họa — không phải số liệu thật.</Notice>}
          {/* A route's code arrives on first visit (or on hover of its link);
            * until then the content area holds a skeleton, the shell stays. */}
          <Suspense fallback={<LoadingSkeleton variant="page" />}>{children}</Suspense>
        </main>
      </div>
    </div>
  )
}

/* --------------------------------------------------------------- Router */

function render(path: string, viewer: CurrentUser): ReactNode {
  const name = routeName(path)
  const id = routeParam(path) ?? ''
  switch (name) {
    case 'organizations':
      return <OrganizationsPage />
    case 'performance':
      return <PerformancePage organizationId={viewer.organizationId} />
    case 'farms':
      return <FarmsPage organizationId={viewer.organizationId} />
    case 'farmer-accounts':
      return <FarmerAccountsPage organizationId={viewer.organizationId} role={viewer.role} />
    case 'farmer-account-new':
      return <ProvisionFarmerPage organizationId={viewer.organizationId} role={viewer.role} />
    case 'seasons':
      return <SeasonsWorkspace organizationId={viewer.organizationId} />
    case 'data-gaps':
      return <SeasonsWorkspace organizationId={viewer.organizationId} focus="missing" />
    case 'ops-carbon':
      return <SeasonsWorkspace organizationId={viewer.organizationId} focus="carbon" />
    case 'farm':
      return <FarmPage id={id} />
    case 'plot':
      return <PlotPage id={id} role={viewer.role} />
    case 'season':
      return <SeasonHub id={id} tab="overview" role={viewer.role} organizationId={viewer.organizationId} />
    case 'activities':
      return <SeasonHub id={id} tab="activities" role={viewer.role} organizationId={viewer.organizationId} />
    case 'season-performance':
      return <SeasonHub id={id} tab="performance" role={viewer.role} organizationId={viewer.organizationId} />
    case 'season-mrv':
      return <SeasonHub id={id} tab="mrv" role={viewer.role} organizationId={viewer.organizationId} />
    case 'carbon':
      return <SeasonHub id={id} tab={'carbon' as SeasonTab} role={viewer.role} organizationId={viewer.organizationId} />
    case 'mrv':
      return <MrvPage role={viewer.role} />
    case 'notFound':
      return (
        <div className="state">
          <div className="state__icon">
            <Ico name="search" size={18} />
          </div>
          <p className="state__title">Không tìm thấy trang</p>
          <p className="state__body">Đường dẫn không tồn tại trong hệ thống.</p>
          <div className="state__actions">
            <button className="btn btn--ghost" onClick={() => go('/dashboard')}>
              Về Tổng quan
            </button>
          </div>
        </div>
      )
    default:
      // The operations queue is the Management home; the old KPI dashboard
      // stays available as the organisation overview under "Tổ chức / HTX".
      return <OperationsOverview organizationId={viewer.organizationId} />
  }
}

/** A farmer stays inside /farmer/*; anyone else stays out of it, and leaving
 * /login always lands on the role's home. Takes role/path explicitly (never
 * reads them back from React state) so callers can invoke it right where a
 * role was just resolved, with no risk of acting on a stale value from a
 * race between two effects (see below). */
function applyRoleRedirect(role: string, currentPath: string) {
  const home = role === 'farmer' ? '/farmer' : '/dashboard'
  if (currentPath === '/login') {
    go(home)
    return
  }
  if (role === 'farmer' && !currentPath.startsWith('/farmer')) go('/farmer')
  if (role !== 'farmer' && currentPath.startsWith('/farmer')) go('/dashboard')
}

/** Everything a confirmed viewer's cached reads depend on. Two answers with
 *  the same signature may share cached data; any difference drops it. */
function verifiedScope(userId: string, v: CurrentUser): string {
  return JSON.stringify([userId, v.role, v.organizationId, [...(v.writableFarmIds ?? [])].sort(), v.mustChangePassword === true])
}

/** A verified tab re-reads /v1/me when it comes back into view or its token is
 *  refreshed, but never more often than this: switching tabs back and forth
 *  must not turn into a request per switch. */
export const REVALIDATE_MIN_INTERVAL_MS = 60_000
/** A re-check still unanswered after this long no longer blocks the next one
 *  (a hung request must not switch re-checking off for the tab's lifetime). */
export const REVALIDATE_STALE_MS = 30_000

/** /v1/me did not answer, so the backend has not said who this account is.
 *  Tied to the session it was asked for, so a failure can never be shown for
 *  (or hide) a different session. */
interface ViewerFailure { session: Session; status: number; message: string }

/** Neutral on purpose, like the error below: no role label, no navigation and
 *  no business data. Shown while the session is restored and while /v1/me has
 *  not yet confirmed this session's role — the only source of the role. */
function ViewerVerifying({ text }: { text: string }) {
  return (
    <main className="login" aria-busy="true">
      <section className="login-card" data-testid="viewer-verifying">
        <p className="eyebrow">AGRICARBON</p>
        <p role="status">{text}</p>
        <span className="skeleton" style={{ display: 'block', height: 14, borderRadius: 5, marginTop: 12 }} aria-hidden="true" />
        <span className="skeleton" style={{ display: 'block', height: 14, width: '70%', borderRadius: 5, marginTop: 8 }} aria-hidden="true" />
      </section>
    </main>
  )
}

function viewerFailureText(f: ViewerFailure): string {
  if (f.status === 0) return 'Không kết nối được máy chủ để xác minh quyền của tài khoản.'
  if (f.status === 401) return 'Phiên đăng nhập không còn hợp lệ, nên chưa xác minh được quyền của tài khoản.'
  if (f.status === 403) return 'Máy chủ từ chối xác minh quyền của tài khoản này.'
  return `Máy chủ chưa xác minh được quyền của tài khoản (mã ${f.status}).`
}

/** Neutral on purpose: no role label, no navigation, no business screen. A
 *  Manager must not land in the Farmer UI (or anyone in any UI) because the
 *  role read failed — the role is whatever the backend says, and it has not
 *  said yet. */
function ViewerUnverified({ failure, onRetry }: { failure: ViewerFailure; onRetry: () => void }) {
  return (
    <main className="login">
      <section className="login-card" role="alert" data-testid="viewer-unverified">
        <p className="eyebrow">AGRICARBON</p>
        <h1>Chưa xác minh được quyền tài khoản</h1>
        <p>{viewerFailureText(failure)} Chưa thể mở màn hình nghiệp vụ nào cho tới khi máy chủ xác nhận.</p>
        <div className="state__actions">
          <button type="button" className="btn" onClick={onRetry}>Thử lại</button>
          <button type="button" className="btn btn--ghost" onClick={() => void signOut()}>
            {failure.status === 401 ? 'Đăng nhập lại' : 'Đăng xuất'}
          </button>
        </div>
      </section>
    </main>
  )
}

/** The query cache wraps the whole app here (not in main.tsx) so every way
 *  the app is mounted — the browser entry and the DOM tests — gets the same
 *  session-scoped cache. */
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppRoot />
    </QueryClientProvider>
  )
}

function AppRoot() {
  const [path, setPath] = useState(location.pathname)
  const [session, setSession] = useState<Session | null>(null)
  const [viewer, setViewer] = useState<CurrentUser>({ role: 'farmer', organizationId: null })
  const [ready, setReady] = useState(false)
  // The session `viewer` was confirmed for by /v1/me. A business screen renders
  // only while this IS the current session: a new or restored session starts
  // unverified in the very render that introduces it, so no earlier viewer (or
  // a cached role hint) can paint a shell for it, not even for one frame.
  const [verifiedFor, setVerifiedFor] = useState<Session | null>(null)
  const [ended, setEnded] = useState<AuthEndReason | null>(null)
  // Set when /v1/me failed for the live session: the role is unverified and
  // no business screen renders. `meAttempt` re-runs the read (Thử lại).
  const [viewerFailure, setViewerFailure] = useState<ViewerFailure | null>(null)
  const [meAttempt, setMeAttempt] = useState(0)
  // Who /v1/me last confirmed in this tab. When the next answer names another
  // user, role or organisation, the in-memory caches filled under the old
  // scope are dropped before the new shell mounts (see the /v1/me effect).
  const lastVerified = useRef<string | null>(null)
  // The session a /v1/me answer belongs to, cleared *synchronously* when the
  // session ends. The effect's own `alive` flag only flips when React commits
  // the next render, and a /v1/me whose 401 ends the session rejects before
  // that commit — its catch then ran the role redirect from /login to /farmer
  // and the person lost the page to return to (Round 4.4 final gate).
  const liveSession = useRef<Session | null>(null)
  // Bumped when a background re-check finds a different scope: it is the key
  // of the business tree, so every page remounts and nothing rendered under
  // the old role or organisation survives (component state included).
  const [scopeEpoch, setScopeEpoch] = useState(0)
  const lastCheck = useRef(0)
  const checkingSince = useRef(0)

  useEffect(() => {
    const update = () => setPath(location.pathname)
    addEventListener('popstate', update)
    return () => removeEventListener('popstate', update)
  }, [])

  // Sign-out and an expired token end the same way: the session and the viewer
  // are dropped in this render, and the URL is replaced (not pushed) by /login,
  // so nothing signed-in is left mounted and there is no redirect back into
  // the app from a stale session value.
  useEffect(() => onAuthEnded((reason) => {
    liveSession.current = null
    setSession(null)
    setViewer({ role: 'farmer', organizationId: null })
    setEnded(reason)
    // Already on the login screen: nothing to remember and no URL to change,
    // so a late second signal can never become a redirect to itself.
    if (location.pathname !== '/login') {
      const next = reason === 'expired' ? `/login?next=${encodeURIComponent(location.pathname)}` : '/login'
      history.replaceState({}, '', next)
    }
    setPath('/login')
  }), [])

  // Another tab signed a different person in (shared storage and token): this
  // tab switches to that session and verifies it from the neutral skeleton.
  // The previous person's viewer and caches are never shown with it.
  useEffect(() => onSessionReplaced((next) => {
    clearFarmerCache()
    clearOrganizationCache()
    clearQueryData()
    lastVerified.current = null
    setVerifiedFor(null)
    setSession(next)
  }), [])

  useEffect(() => {
    void restoreSession()
      .then(setSession)
      .catch(() => null)
      .finally(() => setReady(true))
  }, [])

  // Real bug found while deep-link-testing the redesign (brief Part 6): this
  // effect and the role-redirect effect below both depended on `session`.
  // When `session` flips from null to a real value, React runs BOTH in the
  // same commit's effect flush, in declaration order — but the redirect
  // effect's closure still sees THIS render's stale readiness/`viewer`
  // (still the pre-session-change default), because a state reset
  // called here only takes effect on a LATER render, not synchronously for
  // a sibling effect in the same flush. Net result: every full page load
  // (deep link or refresh) for a non-farmer role spuriously pushed '/farmer'
  // first, then corrected to '/dashboard' once the real role resolved —
  // silently swallowing whatever route was actually requested. Fixed by
  // performing the redirect directly from the freshly-resolved role value
  // (never a value read back from state), and reserving the separate
  // path-watching effect below for path changes only.
  useEffect(() => {
    setViewerFailure(null)
    if (!session) {
      setViewer({ role: 'farmer', organizationId: null })
      setVerifiedFor(null)
      return
    }
    let alive = true
    liveSession.current = session
    // Still on the temporary password: every business read would be refused,
    // so none is sent; the change form is all this session gets.
    if (mustChangePassword(session)) {
      return () => { alive = false }
    }
    const current = () => alive && liveSession.current === session
    // The cached role hint is NOT used to render anything: until /v1/me
    // answers for this session, the screen is the neutral skeleton. Its one
    // remaining use is a network optimisation with no authority: overlap the
    // Farmer scope read with /v1/me (see prefetchFarmerScope), skipped when
    // this user was last seen as a non-farmer. That read is authorized by the
    // server like any other, lands in the in-memory cache only, and nothing
    // shows it unless /v1/me says Farmer.
    const hintedRole = usingMockData ? null : readViewerHint(session.user.id)?.role
    if (!hintedRole || hintedRole === 'farmer') prefetchFarmerScope()
    void getMe()
      .then((v) => {
        if (!current()) return
        // A different user, role, organisation or farm access than the last
        // answer in this tab: what the caches hold was read under the old
        // scope. Drop all of it before the new shell mounts, so it can only
        // show fresh reads. The query cache is cleared too: its keys carry
        // the user and organisation but not the role, so a role change with
        // the same user and organisation would otherwise reuse the old rows.
        const scope = verifiedScope(session.user.id, v)
        if (lastVerified.current !== null && lastVerified.current !== scope) {
          clearFarmerCache()
          clearOrganizationCache()
          clearQueryData()
        }
        lastVerified.current = scope
        setViewer(v)
        setVerifiedFor(session)
        writeViewerHint(session.user.id, v)
        if (!usingMockData) applyRoleRedirect(v.role, location.pathname)
      })
      .catch((e: unknown) => {
        if (!current()) return
        // Never a fallback role: an unanswered /v1/me used to make every
        // account a Farmer and redirect a Manager to /farmer. The URL stays,
        // the viewer stays unverified, and the person can retry.
        const status = e instanceof ApiError ? e.status : 0
        if (status === 401 || status === 403) clearViewerHint()
        setViewer({ role: 'farmer', organizationId: null })
        setVerifiedFor(null)
        setViewerFailure({ session, status, message: e instanceof Error ? e.message : '' })
      })
    return () => {
      alive = false
    }
  }, [session, meAttempt])

  const verified = session !== null && verifiedFor === session
  const failure = session && viewerFailure?.session === session ? viewerFailure : null

  // The role is read on restore, sign-in and retry. A tab left open would
  // otherwise keep its old role -- and the rows cached under it -- after the
  // role was revoked or changed, until a reload (the server still refuses every
  // new read, but what was loaded stayed on screen). So a verified tab re-reads
  // /v1/me when it is focused or shown again and after a token refresh, at most
  // once per REVALIDATE_MIN_INTERVAL_MS and never twice at a time:
  //  - same scope: nothing changes on screen;
  //  - different scope: every cache is dropped and the business tree remounts
  //    under the newly confirmed role (the role redirect applies);
  //  - 401/403: caches and hint dropped, the neutral "unverified" screen;
  //  - network error / 5xx: nothing is inferred, the confirmed role stays and
  //    the next focus or refresh tries again.
  useEffect(() => {
    if (usingMockData || !session || !verified || failure) return
    lastCheck.current = Date.now()
    const revalidate = () => {
      const now = Date.now()
      if (now - checkingSince.current < REVALIDATE_STALE_MS || now - lastCheck.current < REVALIDATE_MIN_INTERVAL_MS) return
      const started = now
      checkingSince.current = started
      lastCheck.current = now
      void getMe()
        .then((v) => {
          if (liveSession.current !== session) return
          // The shared token now belongs to someone else (another tab signed a
          // different person in): this tab's session is over. Drop what it
          // cached and re-verify with the stored session, from the skeleton.
          if (v.userId && v.userId !== session.user.id) {
            clearFarmerCache()
            clearOrganizationCache()
            clearQueryData()
            lastVerified.current = null
            setVerifiedFor(null)
            void restoreSession().then((s) => { if (liveSession.current === session) setSession(s) }).catch(() => null)
            return
          }
          const scope = verifiedScope(session.user.id, v)
          if (scope === lastVerified.current) return
          clearFarmerCache()
          clearOrganizationCache()
          clearQueryData()
          lastVerified.current = scope
          writeViewerHint(session.user.id, v)
          setViewer(v)
          setScopeEpoch((n) => n + 1)
          applyRoleRedirect(v.role, location.pathname)
        })
        .catch((e: unknown) => {
          if (liveSession.current !== session) return
          const status = e instanceof ApiError ? e.status : 0
          if (status !== 401 && status !== 403) return
          clearViewerHint()
          clearFarmerCache()
          clearOrganizationCache()
          clearQueryData()
          lastVerified.current = null
          setViewer({ role: 'farmer', organizationId: null })
          setVerifiedFor(null)
          setViewerFailure({ session, status, message: e instanceof Error ? e.message : '' })
        })
        .finally(() => { if (checkingSince.current === started) checkingSince.current = 0 })
    }
    const onVisible = () => { if (document.visibilityState === 'visible') revalidate() }
    addEventListener('focus', revalidate)
    document.addEventListener('visibilitychange', onVisible)
    const offRefreshed = onSessionRefreshed(revalidate)
    return () => {
      removeEventListener('focus', revalidate)
      document.removeEventListener('visibilitychange', onVisible)
      offRefreshed()
    }
  }, [session, verified, failure])

  // Ongoing protection once the viewer is verified for this session: catches
  // a manual URL edit into the "wrong side" while already logged in. Keyed
  // only on `path` (not session/viewer) so it never re-fires from the same
  // commit as the effect above, and it does nothing until /v1/me has
  // confirmed the role of the current session.
  useEffect(() => {
    if (usingMockData || !session || !verified || failure) return
    applyRoleRedirect(viewer.role, path)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path])

  useEffect(() => {
    document.title = 'AgriCarbon — Dashboard'
  }, [])

  if (!ready) return <ViewerVerifying text="Đang khôi phục phiên…" />

  // Before the /login check: a flagged sign-in stays on /login (the role
  // redirect needs /v1/me, which is skipped while the flag is set).
  if (session && (mustChangePassword(session) || (verified && viewer.mustChangePassword))) {
    return <ForcedPasswordChange session={session} done={(s) => {
      setViewer({ role: 'farmer', organizationId: null })
      setVerifiedFor(null)
      setSession(s)
    }} />
  }

  // Explicit mock mode is an isolated development/test path.  It must not
  // silently affect normal production mode, but it also must not be blocked by
  // the real Supabase credentials loaded from .env during the mock smoke test.
  const authRequired = Boolean(!usingMockData && import.meta.env.VITE_SUPABASE_URL && import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY && !session)
  if (path === '/login' || authRequired) {
    return <Login ended={ended} done={(s) => {
      setEnded(null)
      // Back to where an expired session interrupted the person, if it was a
      // page of this app; the role redirect still applies once /v1/me answers.
      const next = new URLSearchParams(location.search).get('next')
      if (next && next.startsWith('/') && !next.startsWith('//')) { history.replaceState({}, '', next); setPath(next) }
      setSession(s)
    }} />
  }
  if (failure) {
    return <ViewerUnverified failure={failure} onRetry={() => {
      setViewerFailure(null)
      setMeAttempt((n) => n + 1)
    }} />
  }
  // Every business screen below needs a role /v1/me confirmed for THIS session.
  if (session && !verified) return <ViewerVerifying text="Đang xác minh quyền tài khoản…" />

  if ((usingMockData && path.startsWith('/farmer')) || (!usingMockData && viewer.role === 'farmer')) {
    return (
      <Suspense key={scopeEpoch} fallback={<main className="login">Đang tải…</main>}>
        <FarmerExperience session={session} viewer={viewer} path={path.startsWith('/farmer') ? path : '/farmer'} />
      </Suspense>
    )
  }

  return (
    <AppShell key={scopeEpoch} session={session} viewer={viewer} path={path}>
      {render(path, viewer)}
    </AppShell>
  )
}
