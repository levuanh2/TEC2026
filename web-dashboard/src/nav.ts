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
    // Kept as "Hiệu suất" so a season being viewed still docks here as a
    // context link (see ContextLink below) instead of disappearing.
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

export interface ContextLink { to: string; label: string; group: 'Quản lý' | 'Hiệu suất' }

/** Build the nav for a role, injecting the plot/season the user is currently viewing. */
export function buildNav(role: Role, context: ContextLink[]): NavGroup[] {
  const allowed = new Set(visibleNav(role))
  return STATIC.map((g) => {
    const items = g.items.filter((it) => allowed.has(it.to))
    const ctx = context.filter((c) => c.group === g.label)
    return {
      ...g,
      items: [...items, ...ctx.map((c) => ({ to: c.to, label: c.label, icon: 'chevron', context: true } as NavItem & { context?: boolean }))],
    }
  }).filter((g) => g.items.length > 0)
}
