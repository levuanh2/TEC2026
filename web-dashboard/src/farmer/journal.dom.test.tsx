// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { Activity } from '../types'
import { Timeline } from './journal'

/* Regression: the open detail drawer must show live data, not a snapshot.
 *
 * The drawer used to keep the clicked `Activity` object in state. Editing an
 * activity invalidates and refetches that season's reads, but the already-open
 * drawer went on showing the values from before the edit — indefinitely, since
 * nothing ever replaced that captured object. It now holds the row's id and
 * re-resolves it from the current list on every render.
 *
 * This test fails against the snapshot implementation. */

const activity = (amountKg: number): Activity => ({
  id: 'act-1',
  cropSeasonId: 'season-1',
  occurredAt: '2026-09-12',
  type: 'fertilizer',
  detail: JSON.stringify({ fertilizer_name: 'Urê', amount_kg: amountKg }),
  recorder: 'QA Farmer',
  source: 'web',
})

/** The `<dd>` under the "Khối lượng (kg)" term inside the open drawer. */
function amountValue(): string | undefined {
  const rows = screen.getByRole('dialog').querySelectorAll('.fw-detail > div')
  for (const row of rows) {
    if (row.querySelector('dt')?.textContent === 'Khối lượng (kg)') {
      return row.querySelector('dd')?.textContent ?? undefined
    }
  }
  return undefined
}

describe('journal detail drawer', () => {
  afterEach(cleanup)

  it('shows the refreshed values when the list updates while it is open', async () => {
    const { rerender } = render(<Timeline activities={[activity(12)]} />)

    await act(async () => { screen.getByRole('button', { name: /Urê/ }).click() })
    // The amount row specifically — the drawer also renders a date that happens
    // to contain "12", which a whole-text assertion would match by accident.
    expect(amountValue()).toBe('12')

    // The post-edit refetch lands: same row, new values.
    rerender(<Timeline activities={[activity(18)]} />)

    expect(amountValue()).toBe('18')
  })

  it('closes itself if the open row disappears from the list', async () => {
    const { rerender } = render(<Timeline activities={[activity(12)]} />)
    await act(async () => { screen.getByRole('button', { name: /Urê/ }).click() })
    expect(screen.getByRole('dialog')).toBeTruthy()

    rerender(<Timeline activities={[]} />)   // deleted elsewhere

    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
