// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FarmPerformance, OrgMetrics } from '../api/organizations'

/* Round 4.4 gate — Management must not call a partly harvested farm
 * "unharvested", must not publish a cooperative figure from incomplete data,
 * and must not show developer vocabulary.
 *
 * Fixture: one farm, two seasons. Season A has 5 200 kg on record, season B
 * has no harvest. The payload below is what the backend sends for that farm
 * (`farm_performance` in backend/infrastructure/read_repo.py): its yield_kg is
 * summed only when every season has one, so it is null here, the per-kg
 * figures are null, and data_status is "partial". The organisation metrics are
 * null for the same reason. Nothing in the payload carries the 5 200 kg, so the
 * UI must not show it either. */

const ALL_NULL: OrgMetrics = {
  waterPerKg: null, fertilizerPerKg: null, co2ePerKg: null, costPerKg: null,
  yieldKg: null, waterM3: null, fertilizerKg: null, totalCo2eKg: null,
  completeness: { water: false, fertilizer: false, cost: false, carbon: false },
}
const PARTIAL: FarmPerformance = {
  farmId: 'f1', farmName: 'Hộ demo 1', areaHa: 1.2, yieldKg: null,
  waterPerKg: null, fertilizerPerKg: null, co2ePerKg: null, costPerKg: null, dataStatus: 'partial',
}

let farms: FarmPerformance[] = [PARTIAL]
const calls: string[] = []
vi.mock('../api/organizations', () => ({
  getOrganization: async () => { calls.push('organization'); return { id: 'o', code: 'O', name: 'HTX Demo', organizationType: 'cooperative', isActive: true } },
  getOrganizationMetrics: async () => { calls.push('metrics'); return ALL_NULL },
  getFarmPerformance: async () => { calls.push('farm-performance'); return farms },
}))
const perSeason = vi.fn()
vi.mock('../api/metrics', () => ({ getResourceMetrics: (...a: unknown[]) => { perSeason(...a); return Promise.resolve(null) } }))
const farmsApi = vi.fn()
vi.mock('../api/farms', () => ({
  usingMockData: false,
  listFarms: (...a: unknown[]) => { farmsApi(...a); return Promise.resolve([]) },
  getFarmCropSeasons: (...a: unknown[]) => { farmsApi(...a); return Promise.resolve([]) },
  getPlotsForFarm: (...a: unknown[]) => { farmsApi(...a); return Promise.resolve([]) },
}))

const { PerformancePage } = await import('./performance')

/** Words a cooperative manager should never read on the workspace. */
const DEV_TERMS = /\b(endpoint|API|payload|batch|null|undefined|NaN|yield_kg|data_status|dataStatus|farm_id|season_id)\b/

beforeEach(() => { calls.length = 0; farms = [PARTIAL] })
afterEach(cleanup)

async function renderPage() {
  render(<PerformancePage organizationId="o" />)
  await waitFor(() => expect(screen.getAllByTestId('aggregate-coverage')).toHaveLength(4))
  await waitFor(() => expect(screen.getAllByTestId('aggregate-coverage')[0].textContent).toMatch(/nông hộ/))
  await screen.findByRole('table')
}

describe('Round 4.4: partial harvest (season A 5 200 kg, season B missing)', () => {
  it('never says "Chưa ghi thu hoạch", and says a season is missing instead', async () => {
    await renderPage()
    expect(document.body.textContent).not.toContain('Chưa ghi thu hoạch')
    const row = screen.getByRole('link', { name: /Hộ demo 1/ }).closest('tr')!
    const yieldCell = row.querySelector('td[data-label="Sản lượng"]')!
    expect(yieldCell.textContent).toBe('Có vụ chưa ghi sản lượng thu hoạch')
    expect(yieldCell.querySelector('[data-harvest]')!.getAttribute('data-harvest')).toBe('incomplete')
  })

  it('does not invent the recorded 5 200 kg the payload does not carry', async () => {
    await renderPage()
    expect(document.body.textContent).not.toMatch(/5[.,\s]?200/)
    expect(document.body.textContent).not.toMatch(/(^|\s)0 kg/)
  })

  it('does not mark the farm complete', async () => {
    await renderPage()
    const row = screen.getByRole('link', { name: /Hộ demo 1/ }).closest('tr')!
    expect(within(row).queryByText('Đầy đủ dữ liệu')).toBeNull()
    expect(within(row).getByText('Thiếu một phần')).toBeTruthy()
  })

  it('publishes no cooperative figure while coverage is short', async () => {
    await renderPage()
    expect(document.querySelectorAll('.agg__value')).toHaveLength(0)
    for (const n of screen.getAllByTestId('aggregate-coverage')) {
      expect(n.textContent).toBe('Chưa công bố chỉ số toàn HTX — 1/1 nông hộ còn thiếu dữ liệu.')
    }
  })

  it('each missing list names exactly that farm, why, and links to it', async () => {
    await renderPage()
    const toggles = screen.getAllByRole('button', { name: '1 nông hộ thiếu dữ liệu' })
    expect(toggles).toHaveLength(4)
    for (const t of toggles) {
      expect(t.getAttribute('aria-expanded')).toBe('false')
      fireEvent.click(t)
      expect(t.getAttribute('aria-expanded')).toBe('true')
      const list = document.getElementById(t.getAttribute('aria-controls')!)!
      expect(list.hidden).toBe(false)
      const items = within(list).getAllByRole('listitem')
      expect(items).toHaveLength(1)
      expect(within(items[0]).getByRole('link').getAttribute('href')).toBe('/farms/f1')
      expect(items[0].textContent).toBe('Hộ demo 1Có vụ chưa ghi sản lượng thu hoạch')
    }
  })

  it('a farm with no season at all is the only one called "no harvest"', async () => {
    farms = [PARTIAL, { ...PARTIAL, farmId: 'f2', farmName: 'Hộ demo 2', areaHa: 0, dataStatus: 'missing' }]
    await renderPage()
    const cell = (name: RegExp) => screen.getByRole('link', { name }).closest('tr')!.querySelector('td[data-label="Sản lượng"]')!.textContent
    expect(cell(/Hộ demo 1/)).toBe('Có vụ chưa ghi sản lượng thu hoạch')
    expect(cell(/Hộ demo 2/)).toBe('Chưa có sản lượng thu hoạch')
  })

  it('a fully harvested farm shows its total', async () => {
    farms = [{ ...PARTIAL, yieldKg: 5200 }]
    await renderPage()
    const cell = screen.getByRole('link', { name: /Hộ demo 1/ }).closest('tr')!.querySelector('td[data-label="Sản lượng"]')!
    expect(cell.textContent).toMatch(/^5\.200\skg$/)
  })
})

describe('Round 4.4: no developer vocabulary on the workspace', () => {
  it('none in the rendered page, with every disclosure open', async () => {
    await renderPage()
    for (const t of screen.getAllByRole('button', { name: /nông hộ thiếu dữ liệu/ })) fireEvent.click(t)
    expect(document.body.textContent).not.toMatch(DEV_TERMS)
  })
})

describe('Round 4.4: request budget does not grow with the tenant', () => {
  it('1 farm and 40 farms read the same three endpoints once each, no per-season /metrics', async () => {
    await renderPage()
    const small = [...calls].sort()
    cleanup(); calls.length = 0
    farms = Array.from({ length: 40 }, (_, i) => ({ ...PARTIAL, farmId: `f${i}`, farmName: `Hộ ${i}` }))
    await renderPage()
    expect([...calls].sort()).toEqual(small)
    expect(small).toEqual(['farm-performance', 'metrics', 'organization'])
    expect(perSeason).not.toHaveBeenCalled()
    expect(farmsApi).not.toHaveBeenCalled()
  })
})
