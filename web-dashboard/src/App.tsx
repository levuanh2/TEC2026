import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { restoreSession, signIn, signOut } from './api/auth'
import { getMe, readViewerHint, writeViewerHint, type CurrentUser } from './api/me'
import { getOrganization } from './api/organizations'
import { usingMockData } from './api/farms'
import { Ico } from './icons'
import { routeName, routeParam } from './routes'
import { buildNav, type ContextLink } from './nav'
import { go, Link, Notice } from './ui'
import { DashboardPage } from './pages/dashboard'
import { OrganizationsPage, FarmsPage, FarmPage, PlotPage } from './pages/directory'
import { PerformancePage } from './pages/performance'
import { SeasonHub, type SeasonTab } from './pages/season'
import { MrvPage } from './pages/mrv'
import { FarmerExperience } from './farmer/FarmerExperience'
import { prefetchFarmerScope } from './farmer/scope'

const ROLE_LABEL: Record<string, string> = {
  farmer: 'Nông hộ',
  cooperative_manager: 'Quản lý HTX',
  enterprise: 'Doanh nghiệp',
  regulator: 'Cơ quan quản lý',
}

/* --------------------------------------------------------------------- Login */

function Login({ done }: { done: (s: Session) => void }) {
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
      setError(x instanceof Error ? x.message : 'Không thể đăng nhập.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <main className="login">
      <section className="login-card">
        <p className="eyebrow">AGRICARBON</p>
        <h1>Đăng nhập</h1>
        <p>Quản trị hiệu suất tài nguyên &amp; carbon cho lúa gạo. JWT chỉ được chuyển cho FastAPI để kiểm tra RLS.</p>
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
            {busy ? 'Đang đăng nhập…' : 'Đăng nhập'}
          </button>
        </form>
      </section>
    </main>
  )
}

/* ---------------------------------------------------------------- App shell */

function AppShell({ session, viewer, path, children }: { session: Session | null; viewer: CurrentUser; path: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [orgName, setOrgName] = useState<string | null>(null)

  useEffect(() => {
    if (!viewer.organizationId) {
      setOrgName(null)
      return
    }
    let alive = true
    void getOrganization(viewer.organizationId)
      .then((o) => alive && setOrgName(o.name))
      .catch(() => alive && setOrgName(null))
    return () => {
      alive = false
    }
  }, [viewer.organizationId])

  const context = useMemo<ContextLink[]>(() => {
    const id = routeParam(path)
    if (!id) return []
    if (path.startsWith('/plots/')) return [{ to: `/plots/${id}`, label: 'Thửa ruộng', group: 'Quản lý' }]
    if (path.startsWith('/crop-seasons/'))
      return [
        { to: `/crop-seasons/${id}`, label: 'Vụ canh tác', group: 'Quản lý' },
        { to: `/crop-seasons/${id}/carbon`, label: 'Carbon vụ', group: 'Hiệu suất' },
      ]
    return []
  }, [path])

  const groups = buildNav(viewer.role, context)
  const email = session?.user.email ?? 'Chế độ demo'

  return (
    <div className="shell">
      <aside className={`sidebar${open ? ' is-open' : ''}`}>
        <Link to="/dashboard" className="brand">
          AgriCarbon
          <small>Hiệu suất tài nguyên · Carbon · MRV</small>
        </Link>
        <nav className="nav" aria-label="Điều hướng chính">
          {groups.map((g, gi) => (
            <div className="nav-group" key={gi}>
              {g.label && <div className="nav-group__label">{g.label}</div>}
              {g.items.map((it) => {
                const isCtx = (it as { context?: boolean }).context
                const active = path === it.to || (!isCtx && it.to !== '/dashboard' && path.startsWith(it.to))
                return (
                  <Link
                    key={it.to}
                    to={it.to}
                    className={isCtx ? 'is-context' : undefined}
                    aria-current={active ? 'page' : undefined}
                    onClick={() => setOpen(false)}
                  >
                    {!isCtx && <span className="nav__ico"><Ico name={it.icon} size={15} /></span>}
                    {it.label}
                  </Link>
                )
              })}
            </div>
          ))}
        </nav>
        <div className="sidebar__foot">
          <span className="avatar" aria-hidden="true">
            {email[0]?.toUpperCase()}
          </span>
          <span className="sidebar__id">
            <b>{email}</b>
            <small>{ROLE_LABEL[viewer.role] ?? viewer.role}</small>
            {session && (
              <button className="link" onClick={() => void signOut().then(() => go('/login'))}>
                Đăng xuất
              </button>
            )}
          </span>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar__ctx">
            <button className="menu-btn" aria-label="Mở menu" onClick={() => setOpen((o) => !o)}>
              <Ico name="menu" size={20} />
            </button>
            <span className="org-chip">
              {orgName ?? 'Chưa gán tổ chức'}
              {orgName && <small> · phạm vi hiện tại</small>}
            </span>
          </div>
          <span className="role-chip">{ROLE_LABEL[viewer.role] ?? viewer.role}</span>
        </header>
        <main className="content">
          {usingMockData && <Notice kind="warning">MOCK DATA — NOT PRODUCTION.</Notice>}
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
    case 'farm':
      return <FarmPage id={id} />
    case 'plot':
      return <PlotPage id={id} />
    case 'season':
      return <SeasonHub id={id} tab="overview" />
    case 'activities':
      return <SeasonHub id={id} tab="activities" />
    case 'season-performance':
      return <SeasonHub id={id} tab="performance" />
    case 'season-mrv':
      return <SeasonHub id={id} tab="mrv" />
    case 'carbon':
      return <SeasonHub id={id} tab={'carbon' as SeasonTab} />
    case 'mrv':
      return <MrvPage />
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
      return <DashboardPage organizationId={viewer.organizationId} />
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

  useEffect(() => {
    const update = () => setPath(location.pathname)
    addEventListener('popstate', update)
    return () => removeEventListener('popstate', update)
  }, [])

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
        if (!alive) return
        setViewer(v)
        writeViewerHint(session.user.id, v)
        if (!usingMockData) applyRoleRedirect(v.role, location.pathname)
      })
      .catch(() => {
        if (!alive) return
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
  if (path === '/login' || authRequired) return <Login done={setSession} />
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
