// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor, fireEvent } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CarbonSeasonStatus } from '../api/carbon'
import { testQueryClient, withQuery } from '../test/withQuery'

/* The Dashboard as rendered: a failed Carbon source is said once and its
 * tiles carry no number; a failed refresh keeps the rows and says they may be
 * old, with a working retry. */

let statusAnswer: () => Promise<{ organization_id: string; items: CarbonSeasonStatus[] }>
vi.mock('../api/carbon', () => ({ getOrganizationCarbonStatus: () => statusAnswer() }))
vi.mock('../api/engine', () => ({ getEngineInfo: () => Promise.resolve({ efConfigVersion: 'v1', engineVersion: 'e', carbonProductionReady: false }) }))
vi.mock('../api/mrv', () => ({ getOrganizationMrvBatches: () => Promise.resolve([]) }))
vi.mock('../api/farms', () => ({
  listFarms: () => Promise.resolve([{ id: 'farm-1', code: 'F1', name: 'Nông hộ 1', plotCount: 1 }]),
  getOrganizationPlotsSeasons: () => Promise.resolve(new Map([['farm-1', {
    plots: [{ id: 'plot-1', farmId: 'farm-1', code: 'P1', name: 'Thửa 1' }],
    seasons: [{ id: 's-1', plotId: 'plot-1', name: 'Vụ 1', status: 'active' }],
  }]])),
}))

const { OperationsOverview } = await import('./operations')
const readiness = { can_calculate: false, blocking_count: 1, input_hash: 'h', ef_config_version: 'v1',
  missing_inputs: [{ code: 'yield', label: 'Sản lượng', detail: '', flow: 'activity' as const, activity_type: 'harvest', blocking: true }] }
const ok = () => Promise.resolve({ organization_id: 'org-1', items: [{ crop_season_id: 's-1', readiness, readiness_error: null, actual: null, actual_error: null }] })

beforeEach(() => { statusAnswer = ok })
afterEach(() => cleanup())

describe('OperationsOverview', () => {
  it('a failed Carbon status: one alert with retry, Carbon tiles show "—"', async () => {
    statusAnswer = () => Promise.reject(new Error('Máy chủ phản hồi quá lâu.'))
    render(withQuery(<OperationsOverview organizationId="org-1" />))
    const alert = await screen.findByTestId('ops-carbon-error')
    expect(alert.textContent).toContain('Máy chủ phản hồi quá lâu.')
    expect(screen.getAllByLabelText('Chưa có số liệu').length).toBeGreaterThanOrEqual(4)
    statusAnswer = ok
    fireEvent.click(alert.querySelector('button')!)
    await waitFor(() => expect(screen.queryByTestId('ops-carbon-error')).toBeNull())
  })

  it('a failed refresh keeps the queue and shows the stale notice', async () => {
    const client = testQueryClient()
    render(withQuery(<OperationsOverview organizationId="org-1" />, client))
    await screen.findByText('Thiếu 1 thông tin để tính phát thải')
    statusAnswer = () => Promise.reject(new Error('503'))
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Tải lại/ })) })
    const notice = await screen.findByTestId('stale-notice')
    expect(notice.textContent).toContain('có thể đã cũ')
    expect(screen.getByText('Thiếu 1 thông tin để tính phát thải')).toBeTruthy()
  })

  it('no organisation: the page explains and requests nothing', () => {
    render(withQuery(<OperationsOverview organizationId={null} />))
    expect(screen.getByText('Chưa gắn với hợp tác xã nào')).toBeTruthy()
  })
})
