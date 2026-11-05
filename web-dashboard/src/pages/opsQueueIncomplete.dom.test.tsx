// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CarbonSeasonStatus } from '../api/carbon'
import { testQueryClient, withQuery } from '../test/withQuery'

/* Regression: the Dashboard said "Không có việc nào cần xử lý lúc này" while a
 * source it builds the queue from had failed (QA 2026-11-04, both builds).
 * "Nothing to do" is a claim about every season; it is made only when every
 * source answered, and a count it never made is never shown as 0. */

type Listing = Map<string, { plots: unknown[]; seasons: unknown[] }>
let farmsAnswer: () => Promise<unknown[]>
let listingAnswer: () => Promise<Listing>
let statusAnswer: () => Promise<{ organization_id: string; items: CarbonSeasonStatus[] }>
let mrvAnswer: () => Promise<unknown[]>
vi.mock('../api/carbon', () => ({ getOrganizationCarbonStatus: () => statusAnswer() }))
vi.mock('../api/engine', () => ({ getEngineInfo: () => Promise.resolve({ efConfigVersion: 'v1', engineVersion: 'e', carbonProductionReady: false }) }))
vi.mock('../api/mrv', () => ({ getOrganizationMrvBatches: () => mrvAnswer() }))
vi.mock('../api/farms', () => ({ listFarms: () => farmsAnswer(), getOrganizationPlotsSeasons: () => listingAnswer() }))

const { OperationsOverview } = await import('./operations')

const farms = () => Promise.resolve([{ id: 'farm-1', code: 'F1', name: 'Nông hộ 1', plotCount: 1 }])
const listing = (): Promise<Listing> => Promise.resolve(new Map([['farm-1', {
  plots: [{ id: 'plot-1', farmId: 'farm-1', code: 'P1', name: 'Thửa 1' }],
  seasons: [{ id: 's-1', plotId: 'plot-1', name: 'Vụ 1', status: 'active' }],
}]]))
const settled = { can_calculate: true, blocking_count: 0, input_hash: 'h', ef_config_version: 'v1', missing_inputs: [] }
const result = { calculated_at: '2026-10-01T00:00:00Z', input_hash: 'h', ef_config_version: 'v1', co2e_per_kg: 1.2, total_co2e_kg: 900 }
const item = (over: Record<string, unknown> = {}) =>
  ({ crop_season_id: 's-1', readiness: settled, readiness_error: null, actual: result, actual_error: null, ...over }) as unknown as CarbonSeasonStatus
/** One season, calculated and current: a genuinely empty queue. */
const nothingToDo = () => Promise.resolve({ organization_id: 'org-1', items: [item()] })
const missingYield = () => Promise.resolve({ organization_id: 'org-1', items: [item({
  actual: null,
  readiness: { ...settled, can_calculate: false, blocking_count: 1,
    missing_inputs: [{ code: 'yield', label: 'Sản lượng', detail: '', flow: 'activity', activity_type: 'harvest', blocking: true }] },
})] })
const fail = (m: string) => () => Promise.reject(new Error(m))
const EMPTY = 'Không có việc nào cần xử lý lúc này.'

beforeEach(() => { farmsAnswer = farms; listingAnswer = listing; statusAnswer = nothingToDo; mrvAnswer = () => Promise.resolve([]) })
afterEach(() => cleanup())

describe('Dashboard queue: incomplete data is never "nothing to do"', () => {
  it('control: every source answered and nothing is outstanding -> the empty message', async () => {
    render(withQuery(<OperationsOverview organizationId="org-1" />))
    expect(await screen.findByTestId('ops-queue-empty')).toBeTruthy()
    expect(screen.getByText(EMPTY)).toBeTruthy()
    expect(screen.queryByTestId('ops-queue-incomplete')).toBeNull()
  })

  it('season list failed: incomplete state with retry, no tile shows a number, retry recovers', async () => {
    listingAnswer = fail('Máy chủ không phản hồi.')
    statusAnswer = missingYield
    render(withQuery(<OperationsOverview organizationId="org-1" />))
    const box = await screen.findByTestId('ops-queue-incomplete')
    expect(box.textContent).toContain('Chưa đọc được đầy đủ dữ liệu')
    expect(box.textContent).toContain('danh sách vụ')
    expect(screen.queryByText(EMPTY)).toBeNull()
    expect(screen.getByTestId('ops-seasons-error').textContent).toContain('Máy chủ không phản hồi.')
    // Counts are over seasons: none is known, so every tile is "—", never 0.
    expect(screen.getAllByLabelText('Chưa có số liệu')).toHaveLength(5)
    expect(screen.queryByTestId('ops-scope')).toBeNull()
    listingAnswer = listing
    fireEvent.click(box.querySelector('button')!)
    expect(await screen.findByText('Thiếu 1 thông tin để tính phát thải')).toBeTruthy()
    expect(screen.queryByTestId('ops-queue-incomplete')).toBeNull()
  })

  it('farms failed: the same incomplete state', async () => {
    farmsAnswer = fail('401')
    render(withQuery(<OperationsOverview organizationId="org-1" />))
    expect((await screen.findByTestId('ops-queue-incomplete')).textContent).toContain('danh sách vụ')
    expect(screen.queryByText(EMPTY)).toBeNull()
  })

  it('MRV failed with an otherwise empty queue: incomplete, MRV tile "—", MRV alert has retry', async () => {
    mrvAnswer = fail('503')
    render(withQuery(<OperationsOverview organizationId="org-1" />))
    const box = await screen.findByTestId('ops-queue-incomplete')
    expect(box.textContent).toContain('hồ sơ MRV')
    expect(box.textContent).not.toContain('danh sách vụ')
    expect(screen.queryByText(EMPTY)).toBeNull()
    const tile = screen.getByText('Hồ sơ MRV chờ xử lý').closest('a')!
    expect(tile.textContent).toContain('—')
    expect(tile.textContent).not.toMatch(/\d/)
    const alert = screen.getByTestId('ops-mrv-error')
    mrvAnswer = () => Promise.resolve([])
    fireEvent.click(alert.querySelector('button')!)
    expect(await screen.findByTestId('ops-queue-empty')).toBeTruthy()
  })

  it('MRV failed with work in the queue: the table stays, marked as possibly incomplete', async () => {
    mrvAnswer = fail('503')
    statusAnswer = missingYield
    render(withQuery(<OperationsOverview organizationId="org-1" />))
    expect(await screen.findByText('Thiếu 1 thông tin để tính phát thải')).toBeTruthy()
    expect(screen.getByTestId('ops-queue-partial').textContent).toContain('hồ sơ MRV')
  })

  it("one season's Carbon state unreadable: the row is in the queue and the queue is marked partial", async () => {
    statusAnswer = () => Promise.resolve({ organization_id: 'org-1', items: [item({ readiness: null, readiness_error: { code: 'x', message: 'Lỗi đọc vụ.' } })] })
    render(withQuery(<OperationsOverview organizationId="org-1" />))
    expect(await screen.findByText('Không đọc được dữ liệu vụ')).toBeTruthy()
    expect(screen.getByTestId('ops-queue-partial').textContent).toContain('trạng thái Carbon của 1 vụ')
    expect(screen.queryByText(EMPTY)).toBeNull()
  })

  it('every source failed: incomplete, all tiles "—", no "nothing to do"', async () => {
    farmsAnswer = fail('x'); listingAnswer = fail('x'); statusAnswer = fail('x'); mrvAnswer = fail('x')
    render(withQuery(<OperationsOverview organizationId="org-1" />))
    expect(await screen.findByTestId('ops-queue-incomplete')).toBeTruthy()
    expect(screen.getAllByLabelText('Chưa có số liệu')).toHaveLength(5)
    expect(screen.queryByText(EMPTY)).toBeNull()
  })

  it('an empty queue from an earlier read whose refresh failed says when it was read', async () => {
    const client = testQueryClient()
    render(withQuery(<OperationsOverview organizationId="org-1" />, client))
    await screen.findByTestId('ops-queue-empty')
    statusAnswer = fail('503')
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Tải lại/ })) })
    const note = await screen.findByTestId('ops-queue-empty-stale')
    expect(note.textContent).toMatch(/đọc lúc \d{2}:\d{2}/)
    expect(note.textContent).toContain('có thể đã cũ')
    expect(screen.getByTestId('stale-notice')).toBeTruthy()
    expect(screen.queryByText(EMPTY)).toBeNull()
    await waitFor(() => expect(screen.queryByTestId('ops-queue-empty')).toBeNull())
  })
})
