import type { IconName } from './icons'
import type { Role } from './types'
import { visibleNav } from './roles'

// Information architecture for the sidebar. Groups reflect the product domain
// (Tổng quan → Quản lý → Hiệu suất → MRV), not the raw DB hierarchy (brief §3).

export interface NavItem { to: string; label: string; icon: IconName }
export interface NavGroup { label?: string; items: NavItem[] }

const STATIC: NavGroup[] = [
  { items: [{ to: '/dashboard', label: 'Tổng quan vận hành', icon: 'overview' }] },
  {
    label: 'Quản lý',
    items: [
      { to: '/farms', label: 'Nông hộ & ruộng', icon: 'farms' },
      { to: '/seasons', label: 'Vụ mùa', icon: 'season' },
      { to: '/data-gaps', label: 'Dữ liệu thiếu', icon: 'warning' },
    ],
  },
  {
    label: 'Hiệu suất',
    items: [
      { to: '/carbon', label: 'Carbon', icon: 'carbon' },
      { to: '/performance', label: 'Hiệu suất vùng', icon: 'analytics' },
    ],
  },
  {
    label: 'MRV',
    items: [{ to: '/mrv', label: 'MRV', icon: 'mrv' }],
  },
  {
    label: 'Khác',
    items: [{ to: '/organizations', label: 'Tổ chức / HTX', icon: 'organization' }],
  },
]

/**
 * Build the nav for a role.
 *
 * Global IA only. The sidebar used to grow an extra "Vụ canh tác"/"Carbon vụ"
 * entry for whatever season was open, so the navigation changed shape as you
 * moved through the app and two of its rows pointed at the page you were
 * already on. Where you are now belongs to the workspace — its breadcrumb and
 * tabs — not to the list of places you can go.
 */
export function buildNav(role: Role): NavGroup[] {
  const allowed = new Set(visibleNav(role))
  return STATIC
    .map((g) => ({ ...g, items: g.items.filter((it) => allowed.has(it.to)) }))
    .filter((g) => g.items.length > 0)
}
