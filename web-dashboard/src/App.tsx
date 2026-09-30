import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { onAuthEnded, restoreSession, signIn, signOut, type AuthEndReason } from './api/auth'
import { getMe, readViewerHint, writeViewerHint, type CurrentUser } from './api/me'
import { getOrganization } from './api/organizations'
import { usingMockData } from './api/farms'
import { Ico } from './icons'
import { routeName, routeParam } from './routes'
import { buildNav } from './nav'
import { go, Link, Notice } from './ui'
import { DashboardPage } from './pages/dashboard'
import { OrganizationsPage, FarmsPage, FarmPage, PlotPage } from './pages/directory'
import { FarmerAccountsPage, ProvisionFarmerPage } from './pages/farmers'
import { PerformancePage } from './pages/performance'
import { SeasonHub, type SeasonTab } from './pages/season'
import { MrvPage } from './pages/mrv'
import { OperationsOverview, SeasonsWorkspace } from './pages/operations'
import { AccountName, Sidebar } from './components/Sidebar'
import { useMobileDrawer } from './components/useMobileDrawer'
import { FarmerExperience } from './farmer/FarmerExperience'
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
          {children}
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
      return <FarmsPage />
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

export default function App() {
  const [path, setPath] = useState(location.pathname)
  const [session, setSession] = useState<Session | null>(null)
  const [viewer, setViewer] = useState<CurrentUser>({ role: 'farmer', organizationId: null })
  const [ready, setReady] = useState(false)
  const [viewerReady, setViewerReady] = useState(false)
  const [ended, setEnded] = useState<AuthEndReason | null>(null)
  // The session a /v1/me answer belongs to, cleared *synchronously* when the
  // session ends. The effect's own `alive` flag only flips when React commits
  // the next render, and a /v1/me whose 401 ends the session rejects before
  // that commit — its catch then ran the role redirect from /login to /farmer
  // and the person lost the page to return to (Round 4.4 final gate).
  const liveSession = useRef<Session | null>(null)

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
  // effect's closure still sees THIS render's stale `viewerReady`/`viewer`
  // (still the pre-session-change default), because `setViewerReady(false)`
  // called here only takes effect on a LATER render, not synchronously for
  // a sibling effect in the same flush. Net result: every full page load
  // (deep link or refresh) for a non-farmer role spuriously pushed '/farmer'
  // first, then corrected to '/dashboard' once the real role resolved —
  // silently swallowing whatever route was actually requested. Fixed by
  // performing the redirect directly from the freshly-resolved role value
  // (never a value read back from state), and reserving the separate
  // path-watching effect below for path changes only.
  useEffect(() => {
    if (!session) {
      setViewer({ role: 'farmer', organizationId: null })
      setViewerReady(true)
      return
    }
    let alive = true
    liveSession.current = session
    const current = () => alive && liveSession.current === session
    // A cached role hint for this same user lets a refresh/deep link paint
    // its shell immediately; /v1/me still revalidates below and its result
    // (not the hint) drives the redirect, exactly as before.
    const hint = usingMockData ? null : readViewerHint(session.user.id)
    if (hint) {
      setViewer(hint)
      setViewerReady(true)
    } else {
      setViewerReady(false)
    }
    // Overlap the Farmer scope read with /v1/me rather than waiting for the
    // role to come back first (see prefetchFarmerScope). Skipped once we
    // already know this user is not a farmer, so a manager's session costs
    // nothing extra.
    if (!hint || hint.role === 'farmer') prefetchFarmerScope()
    void getMe()
      .then((v) => {
        if (!current()) return
        setViewer(v)
        writeViewerHint(session.user.id, v)
        if (!usingMockData) applyRoleRedirect(v.role, location.pathname)
      })
      .catch(() => {
        if (!current()) return
        setViewer({ role: 'farmer', organizationId: null })
        if (!usingMockData) applyRoleRedirect('farmer', location.pathname)
      })
      .finally(() => alive && setViewerReady(true))
    return () => {
      alive = false
    }
  }, [session])

  // Ongoing protection once viewer/viewerReady are already settled: catches
  // a manual URL edit into the "wrong side" while already logged in. Keyed
  // only on `path` (not session/viewer/viewerReady) so it never re-fires
  // from the same commit as the effect above — by the time `path` itself
  // changes, viewer/viewerReady for the current session are already settled.
  useEffect(() => {
    if (usingMockData || !session || !viewerReady) return
    applyRoleRedirect(viewer.role, path)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path])

  useEffect(() => {
    document.title = 'AgriCarbon — Dashboard'
  }, [])

  if (!ready) return <main className="login">Đang khôi phục phiên…</main>

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
  if (session && !viewerReady) return <main className="login">Đang tải phạm vi tài khoản…</main>

  if ((usingMockData && path.startsWith('/farmer')) || (!usingMockData && viewer.role === 'farmer')) {
    return <FarmerExperience session={session} viewer={viewer} path={path.startsWith('/farmer') ? path : '/farmer'} />
  }

  return (
    <AppShell session={session} viewer={viewer} path={path}>
      {render(path, viewer)}
    </AppShell>
  )
}
