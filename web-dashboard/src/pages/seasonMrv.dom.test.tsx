// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

/* Management season hub, MRV section (Round 5.1: one request for every case of
 * the organization). A batch is NOT an MRV case: the season is said to belong
 * to a case only when that case actually lists one of its batches. */
const getOrganizationMrvBatches = vi.fn()
vi.mock('../api/mrv', async (orig) => ({
  ...(await orig<object>()),
  getOrganizationMrvBatches: (...a: unknown[]) => getOrganizationMrvBatches(...a),
}))
vi.mock('../api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))

const { SeasonMrv } = await import('./season')

const BATCHES = [
  { id: 'b-1', batchCode: 'default', name: null, status: 'active', startedOn: '2026-06-01', closedOn: null },
  { id: 'b-2', batchCode: 'LO-2', name: null, status: 'closed', startedOn: null, closedOn: '2026-09-01' },
]
const batch = (id: string, season: string) => ({ productionBatchId: id, batchCode: id, cropSeasonId: season, farmId: 'f', plotId: 'p' })
const linkedState = () => screen.getByTestId('season-mrv-membership').getAttribute('data-linked')

afterEach(() => { cleanup(); getOrganizationMrvBatches.mockReset() })

describe('SeasonMrv', () => {
  it('a case listing one of this season\'s batches: named, linked, and shown on that batch only', async () => {
    getOrganizationMrvBatches.mockResolvedValue([
      { caseId: 'c-1', caseCode: 'MRV-001', status: 'draft', batches: [batch('b-1', 's-1'), batch('x-9', 's-other')] },
      { caseId: 'c-2', caseCode: 'MRV-002', status: 'draft', batches: [batch('x-8', 's-other')] },
    ])
    render(<SeasonMrv seasonId="s-1" organizationId="o-1" batches={BATCHES} />)
    await waitFor(() => expect(linkedState()).toBe('true'))
    expect(getOrganizationMrvBatches).toHaveBeenCalledTimes(1)
    expect(getOrganizationMrvBatches).toHaveBeenCalledWith('o-1')
    expect(document.body.textContent).toContain('Vụ này thuộc hồ sơ MRV MRV-001 qua các lô sản xuất được liên kết.')
    expect(document.body.textContent).not.toContain('MRV-002')
    const rows = screen.getAllByRole('row').map((r) => r.textContent)
    expect(rows.find((r) => r?.includes('Lô mặc định của vụ'))).toContain('MRV-001')
    expect(rows.find((r) => r?.includes('LO-2'))).toContain('Chưa gắn')
    expect(rows.find((r) => r?.includes('LO-2'))).toContain('Chưa ghi nhận')
  })

  it('cases that list only other seasons\' batches: the season is in no case', async () => {
    getOrganizationMrvBatches.mockResolvedValue([
      { caseId: 'c-1', caseCode: 'MRV-001', status: 'draft', batches: [batch('x-9', 's-other')] },
    ])
    render(<SeasonMrv seasonId="s-1" organizationId="o-1" batches={BATCHES} />)
    await waitFor(() => expect(linkedState()).toBe('false'))
    expect(document.body.textContent).toContain('Vụ này chưa thuộc hồ sơ MRV nào.')
    expect(document.body.textContent).toContain('lô chưa được gắn vào hồ sơ MRV nên vụ chưa tham gia MRV')
  })

  it('a failed lookup says it could not check -- it never claims "not in MRV"', async () => {
    getOrganizationMrvBatches.mockRejectedValue(new Error('boom'))
    render(<SeasonMrv seasonId="s-1" organizationId="o-1" batches={BATCHES} />)
    await waitFor(() => expect(linkedState()).toBe('unknown'))
    expect(document.body.textContent).toContain('Chưa kiểm tra được liên kết hồ sơ MRV.')
    expect(document.body.textContent).not.toContain('Vụ này chưa thuộc hồ sơ MRV nào.')
  })

  it('no organization in scope: no request, and no batch yields the empty state', async () => {
    render(<SeasonMrv seasonId="s-1" organizationId={null} batches={[]} />)
    await waitFor(() => expect(linkedState()).toBe('false'))
    expect(getOrganizationMrvBatches).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('Vụ chưa có lô sản xuất')
  })
})
