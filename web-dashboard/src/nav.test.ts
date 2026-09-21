import { describe, expect, it } from 'vitest'
import { buildNav } from './nav'

describe('sidebar IA', () => {
  it('groups reflect the product domain, not the DB hierarchy', () => {
    const labels = buildNav('cooperative_manager', []).map((g) => g.label)
    // Operations IA: the work comes first (Quản lý), then results, then MRV.
    expect(labels).toEqual([undefined, 'Quản lý', 'Hiệu suất', 'MRV', 'Khác'])
  })

  it('a farmer never sees the MRV group', () => {
    const groups = buildNav('farmer', [])
    expect(groups.some((g) => g.label === 'MRV')).toBe(false)
    expect(groups.flatMap((g) => g.items.map((i) => i.to))).toEqual(['/dashboard', '/farms'])
  })

  it('a plot/season the user is viewing is injected as a context link, not a permanent nav item', () => {
    const groups = buildNav('cooperative_manager', [
      { to: '/crop-seasons/s1', label: 'Vụ canh tác', group: 'Quản lý' },
      { to: '/crop-seasons/s1/carbon', label: 'Carbon vụ', group: 'Hiệu suất' },
    ])
    const quanLy = groups.find((g) => g.label === 'Quản lý')!
    expect(quanLy.items.map((i) => i.to)).toContain('/crop-seasons/s1')
    const hieuSuat = groups.find((g) => g.label === 'Hiệu suất')!
    expect(hieuSuat.items.map((i) => i.to)).toContain('/crop-seasons/s1/carbon')
    // context links carry the marker so the shell renders them indented
    expect((quanLy.items.find((i) => i.to === '/crop-seasons/s1') as { context?: boolean }).context).toBe(true)
  })
})
