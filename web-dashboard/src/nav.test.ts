import { describe, expect, it } from 'vitest'
import { buildNav } from './nav'

describe('sidebar IA', () => {
  it('groups reflect the product domain, not the DB hierarchy', () => {
    const labels = buildNav('cooperative_manager').map((g) => g.label)
    // Operations IA: the work comes first (Quản lý), then results, then MRV.
    expect(labels).toEqual([undefined, 'Quản lý', 'Hiệu suất', 'MRV', 'Khác'])
  })

  it('a farmer never sees the MRV group', () => {
    const groups = buildNav('farmer')
    expect(groups.some((g) => g.label === 'MRV')).toBe(false)
    expect(groups.flatMap((g) => g.items.map((i) => i.to))).toEqual(['/dashboard', '/farms'])
  })

  it('the sidebar holds global IA only — the open season never becomes a nav item', () => {
    // It used to inject "Vụ canh tác"/"Carbon vụ" for whatever season was
    // open, so the navigation changed shape as you moved and pointed at the
    // page you were already on. Context belongs to the workspace.
    const items = buildNav('cooperative_manager').flatMap((g) => g.items.map((i) => i.to))
    expect(items.some((to) => to.startsWith('/crop-seasons/'))).toBe(false)
    expect(items.some((to) => to.startsWith('/plots/'))).toBe(false)
    expect(items).toEqual(['/dashboard', '/farms', '/accounts/farmers', '/seasons', '/data-gaps', '/carbon', '/performance', '/mrv', '/organizations'])
  })

  it('only a cooperative manager is offered farmer account provisioning', () => {
    const to = (role: Parameters<typeof buildNav>[0]) => buildNav(role).flatMap((g) => g.items.map((i) => i.to))
    expect(to('cooperative_manager')).toContain('/accounts/farmers')
    expect(to('enterprise_viewer')).not.toContain('/accounts/farmers')
    expect(to('regulator')).not.toContain('/accounts/farmers')
    expect(to('farmer')).not.toContain('/accounts/farmers')
  })
})
