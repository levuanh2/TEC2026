import { describe, expect, it } from 'vitest'
import { activityFields, joinDemoMarker, splitDemoMarker } from './activityPresentation'
import { viewActivity } from '../farmer/activityView'

/* Round 4.1 — the seed marker is split off a note for display and put back on
 * save, so neither the marker nor the farmer's own words are ever lost. */

const MARKER = 'DEMO / SYNTHETIC DATA — NOT FIELD DATA, NOT OFFICIAL MRV DATA'

describe('demo marker split/join', () => {
  it('separates the marker from the note', () => {
    expect(splitDemoMarker(MARKER)).toEqual({ marker: MARKER, text: '' })
    expect(splitDemoMarker(`Tưới sáng\n\n${MARKER}`)).toEqual({ marker: MARKER, text: 'Tưới sáng' })
    expect(splitDemoMarker('Ghi chú thật')).toEqual({ marker: null, text: 'Ghi chú thật' })
    expect(splitDemoMarker(null)).toEqual({ marker: null, text: '' })
  })

  it('round-trips without losing either part', () => {
    for (const note of [MARKER, `Tưới sáng\n\n${MARKER}`]) {
      const { marker, text } = splitDemoMarker(note)
      expect(joinDemoMarker(marker, text)).toBe(note)
    }
    expect(joinDemoMarker(null, '  ')).toBeNull()
    expect(joinDemoMarker(null, 'Ghi chú')).toBe('Ghi chú')
  })

  it('surfaces show the farmer\'s own words and never the English marker', () => {
    const detail = JSON.stringify({ method: 'awd', water_volume_m3: 10, note: `Tưới sáng\n\n${MARKER}` })
    expect(viewActivity({ type: 'irrigation', detail }).note).toBe('Tưới sáng')
    expect(viewActivity({ type: 'irrigation', detail: JSON.stringify({ note: MARKER }) }).note).toBeNull()
    const rows = activityFields(detail, 'irrigation')
    expect(rows.map((r) => r.value).join(' ')).not.toMatch(/SYNTHETIC/)
  })
})
