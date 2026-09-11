import type { Role } from './types'
import { visibleNav } from './roles'

// Information architecture for the sidebar. Groups reflect the product domain
// (Tổng quan → Quản lý → Hiệu suất → MRV), not the raw DB hierarchy (brief §3).

export interface NavItem { to: string; label: string; icon: string }
export interface NavGroup { label?: string; items: NavItem[] }

const STATIC: NavGroup[] = [
  { items: [{ to: '/dashboard', label: 'Tổng quan', icon: '◧' }] },
  {
    label: 'Quản lý',
    items: [
      { to: '/organizations', label: 'Tổ chức / HTX', icon: '⬡' },
      { to: '/farms', label: 'Nông hộ', icon: '⌂' },
    ],
  },
  {
    label: 'Hiệu suất',
    items: [{ to: '/performance', label: 'Hiệu suất vùng', icon: '◈' }],
  },
  {
    label: 'MRV',
    items: [{ to: '/mrv', label: 'Hồ sơ MRV', icon: '✓' }],
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
      items: [...items, ...ctx.map((c) => ({ to: c.to, label: c.label, icon: '·', context: true } as NavItem & { context?: boolean }))],
    }
  }).filter((g) => g.items.length > 0)
}
