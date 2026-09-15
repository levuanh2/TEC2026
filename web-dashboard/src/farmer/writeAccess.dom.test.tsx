// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Activity, CropSeason, Plot } from '../types'
import { canWriteFarm, FarmWriteAccess } from './writeAccess'

/* B3: a farm `viewer` is read-only. FastAPI and RLS refuse the write; the
 * Farmer UI must not offer journal write controls that can only fail. */

const plot = { id: 'plot-1', farmId: 'farm-1', code: 'P1', name: 'Thửa 1' } as Plot
const season = { id: 'season-1', plotId: 'plot-1', name: 'Hè Thu 2026', status: 'active' } as unknown as CropSeason
const ctx = { season, plot }
const activity: Activity = {
  id: 'act-1', cropSeasonId: 'season-1', occurredAt: '2026-09-12', type: 'fertilizer',
  detail: JSON.stringify({ fertilizer_name: 'Urê', amount_kg: 12 }), recorder: 'QA Farmer', source: 'web',
}
const ready = <T,>(data: T) => ({ data, loading: false, error: null, reload: () => undefined })

vi.mock('./scope', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./scope')>()
  return {
    ...actual,
    useScope: () => ready({ farms: [], plots: [plot], seasons: [season] }),
    seasonsOf: () => [ctx],
    primarySeason: () => ctx,
    useActivities: () => ready([activity]),
  }
})

const { FarmerJournalPage } = await import('./pages/Journal')

function renderJournal(writable: string[] | undefined) {
  return render(<FarmWriteAccess.Provider value={writable}><FarmerJournalPage /></FarmWriteAccess.Provider>)
}

afterEach(cleanup)

describe('canWriteFarm', () => {
  it('allows owner/editor farms, denies others, and keeps unknown permissive', () => {
    expect(canWriteFarm(['farm-1'], 'farm-1')).toBe(true)
    expect(canWriteFarm(['farm-1'], 'farm-2')).toBe(false)
    expect(canWriteFarm([], 'farm-1')).toBe(false)
    expect(canWriteFarm(['farm-1'], undefined)).toBe(false)
    expect(canWriteFarm(undefined, 'farm-1')).toBe(true)
  })
})

describe('Farmer journal write affordances', () => {
  it('a viewer sees the journal but no add, edit or delete controls', () => {
    renderJournal([])
    expect(screen.getByRole('button', { name: /Urê/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Ghi hoạt động/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Sửa bản ghi/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Xóa bản ghi/ })).toBeNull()
  })

  it('an owner/editor keeps the add, edit and delete controls', () => {
    renderJournal(['farm-1'])
    expect(screen.getByRole('button', { name: /Ghi hoạt động/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Sửa bản ghi/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Xóa bản ghi/ })).toBeTruthy()
  })
})
