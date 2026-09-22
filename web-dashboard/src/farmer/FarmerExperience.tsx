import './farmer.css'
import { useEffect, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import type { CurrentUser } from '../api/me'
import { Link } from '../ui'
import { initials } from './activityView'
import { Ico, type IconName } from './icons'
import { Empty, IconTile, Sk } from './kit'
import { FarmerAccountPage } from './pages/Account'
import { FarmerFarmPage, FarmerFarmsPage, FarmerPlotPage } from './pages/Farms'
import { FarmerHome } from './pages/Home'
import { FarmerJournalPage } from './pages/Journal'
import { FarmerCarbonPage } from './pages/FarmerCarbon'
import { FarmerPerformancePage } from './pages/Performance'
import { SeasonWorkspace } from './pages/Season'
import { prefetchNav, prefetchSeason, primarySeason, useScope } from './scope'
import { FarmWriteAccess } from './writeAccess'

/** `short` is the phone label: six tabs at 390px cannot carry 'Ruộng / Vụ mùa'. */
type NavItem = { to: string; label: string; icon: IconName; short?: string }

const NAV: { group: string; items: NavItem[] }[] = [
  { group: 'Tổng quan', items: [{ to: '/farmer', label: 'Tổng quan', icon: 'home' }] },
  { group: 'Canh tác', items: [{ to: '/farmer/journal', label: 'Nhật ký', icon: 'journal' }, { to: '/farmer/farms', label: 'Ruộng / Vụ mùa', icon: 'farm', short: 'Ruộng' }] },
  // Carbon is a destination of its own, not a tab a farmer has to find inside
  // a season: /farmer/carbon resolves to the season they are working on.
  { group: 'Theo dõi', items: [{ to: '/farmer/performance', label: 'Hiệu suất', icon: 'performance' }, { to: '/farmer/carbon', label: 'Carbon', icon: 'carbon' }] },
  { group: 'Tài khoản', items: [{ to: '/farmer/account', label: 'Tôi', icon: 'account' }] },
]
const TABS = NAV.flatMap((g) => g.items)

function isCurrent(to: string, path: string): boolean {
  if (to === '/farmer') return path === '/farmer'
  if (to === '/farmer/carbon') return path === '/farmer/carbon' || /^\/farmer\/crop-seasons\/[^/]+\/carbon$/.test(path)
  if (to === '/farmer/farms') return /^\/farmer\/(farms|plots|crop-seasons)(\/|$)/.test(path) && !path.endsWith('/carbon')
  return path === to || path.startsWith(`${to}/`)
}

function FarmerShell({ session, viewer, path, children }: { session: Session | null; viewer: CurrentUser; path: string; children: ReactNode }) {
  const scope = useScope()
  const primary = primarySeason(scope.data)
  const email = session?.user.email ?? null
  const name = viewer.fullName?.trim() || email || 'Tài khoản nông hộ'
  const avatar = initials(viewer.fullName, email)
  const warm = (to: string) => () => prefetchNav(to)

  return (
    <div className="fw fw-shell">
      {/* First stop for a keyboard or screen-reader user: the sidebar is a
        * long list of links to walk past on every page. */}
      <a className="skip-link" href="#main">Bỏ qua điều hướng, tới nội dung chính</a>
      <aside className="fw-side">
        <Link to="/farmer" className="fw-brand">
          <b>AgriCarbon</b><small>Nông hộ</small>
        </Link>
        <nav className="fw-nav" aria-label="Điều hướng nông hộ">
          {NAV.map((group) => (
            <div key={group.group} className="fw-nav__group">
              <p className="fw-nav__label" aria-hidden="true">{group.group}</p>
              {group.items.map((item) => (
                <Link key={item.to} to={item.to} className="fw-nav__item" aria-current={isCurrent(item.to, path) ? 'page' : undefined} onMouseEnter={warm(item.to)} onFocus={warm(item.to)}>
                  <Ico name={item.icon} />{item.label}
                </Link>
              ))}
            </div>
          ))}
        </nav>
        {/* The sidebar names who is signed in and links to the one page that
          * can act on it. Sign-out used to sit here as well as on that page,
          * so both were on screen at once and neither was the obvious one. */}
        <Link to="/farmer/account" className="fw-profile" aria-label={`Tài khoản của ${name}`}>
          <span className="fw-avatar" aria-hidden="true">{avatar}</span>
          <span className="fw-profile__id">
            <b title={name}>{name}</b>
            <small>Xem tài khoản</small>
          </span>
        </Link>
      </aside>

      <div className="fw-main">
        <header className="fw-topbar">
          <Link to="/farmer" className="fw-topbar__brand" aria-label="AgriCarbon — Tổng quan">AgriCarbon</Link>
          {primary ? (
            <Link to={`/farmer/crop-seasons/${primary.season.id}`} className="fw-ctx" onMouseEnter={() => prefetchSeason(primary.season.id)} aria-label={`Vụ đang canh tác: ${primary.season.name}${primary.plot ? `, ${primary.plot.name}` : ''}`}>
              <IconTile name="seeding" tone="leaf" size="sm" />
              <span className="fw-ctx__text">{primary.season.name}{primary.plot && <small> · {primary.plot.name}</small>}</span>
            </Link>
          ) : scope.loading ? (
            <span className="fw-ctx fw-ctx--sk" aria-hidden="true"><Sk w={140} h={12} /></span>
          ) : null}
          <span className="fw-topbar__meta"><Ico name="pin" />{primary?.farm ? primary.farm.name : 'Khu vực nông hộ'}</span>
          <Link to="/farmer/account" className="fw-avatar" aria-label="Tài khoản của bạn">{avatar}</Link>
        </header>
        <main className="fw-content" id="main" tabIndex={-1}>{children}</main>
      </div>

      <nav className="fw-bottom" aria-label="Điều hướng nông hộ trên điện thoại">
        {TABS.map((item) => (
          <Link key={item.to} to={item.to} aria-current={isCurrent(item.to, path) ? 'page' : undefined} onFocus={warm(item.to)} onTouchStart={warm(item.to)}>
            <span className="fw-bottom__ico"><Ico name={item.icon} /></span>{item.short ?? item.label}
          </Link>
        ))}
      </nav>
    </div>
  )
}

export function FarmerExperience({ session, viewer, path }: { session: Session | null; viewer: CurrentUser; path: string }) {
  const page = farmerRoute(path)
  const id = farmerParam(path)
  const scrollKey = page.startsWith('season') ? `season:${id}` : path
  useEffect(() => { window.scrollTo({ top: 0 }) }, [scrollKey])

  let content: ReactNode
  switch (page) {
    case 'home': content = <FarmerHome viewer={viewer} />; break
    case 'journal': content = <FarmerJournalPage />; break
    case 'farms': content = <FarmerFarmsPage />; break
    case 'farm': content = <FarmerFarmPage id={id!} />; break
    case 'plot': content = <FarmerPlotPage id={id!} />; break
    case 'season': content = <SeasonWorkspace id={id!} tab="overview" />; break
    case 'season-journal': content = <SeasonWorkspace id={id!} tab="journal" />; break
    case 'season-performance': content = <SeasonWorkspace id={id!} tab="performance" />; break
    case 'season-carbon': content = <SeasonWorkspace id={id!} tab="carbon" />; break
    case 'performance': content = <FarmerPerformancePage />; break
    case 'carbon': content = <FarmerCarbonPage />; break
    case 'account': content = <FarmerAccountPage session={session} viewer={viewer} />; break
    default: content = <Empty icon="search" title="Không tìm thấy trang" body="Đường dẫn này không thuộc khu vực nông hộ." action={<Link to="/farmer" className="fw-btn fw-btn--soft">Về Tổng quan</Link>} />
  }
  return (
    <FarmWriteAccess.Provider value={viewer.writableFarmIds}>
      <FarmerShell session={session} viewer={viewer} path={path}>{content}</FarmerShell>
    </FarmWriteAccess.Provider>
  )
}

type FarmerRoute = 'home' | 'journal' | 'farms' | 'farm' | 'plot' | 'season' | 'season-journal' | 'season-performance' | 'season-carbon' | 'performance' | 'carbon' | 'account' | 'not-found'
function farmerRoute(path: string): FarmerRoute {
  if (path === '/farmer') return 'home'
  if (path === '/farmer/journal') return 'journal'
  if (path === '/farmer/farms') return 'farms'
  if (path === '/farmer/performance') return 'performance'
  if (path === '/farmer/carbon') return 'carbon'
  if (path === '/farmer/account') return 'account'
  if (/^\/farmer\/farms\/[^/]+$/.test(path)) return 'farm'
  if (/^\/farmer\/plots\/[^/]+$/.test(path)) return 'plot'
  if (/^\/farmer\/crop-seasons\/[^/]+\/journal$/.test(path)) return 'season-journal'
  if (/^\/farmer\/crop-seasons\/[^/]+\/performance$/.test(path)) return 'season-performance'
  if (/^\/farmer\/crop-seasons\/[^/]+\/carbon$/.test(path)) return 'season-carbon'
  if (/^\/farmer\/crop-seasons\/[^/]+$/.test(path)) return 'season'
  return 'not-found'
}
function farmerParam(path: string): string | null { return path.match(/^\/farmer\/(?:farms|plots|crop-seasons)\/([^/]+)/)?.[1] ?? null }
