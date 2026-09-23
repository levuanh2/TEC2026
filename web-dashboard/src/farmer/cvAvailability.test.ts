import { describe, expect, it } from 'vitest'
import { cvAvailability } from './CvCheck'

/* Round 4 §6.3 — the leaf check is not offered when the server cannot run it:
 * a card that ends in "Tạm thời chưa dùng được" is a dead feature. */
describe('cvAvailability', () => {
  it('hides the feature when the CV service answers 503 not configured', () => {
    expect(cvAvailability({ loading: false, error: 'CV service is not configured.' })).toBe('no')
  })
  it('stays undecided while the probe is loading, so nothing flashes in and out', () => {
    expect(cvAvailability({ loading: true })).toBe('loading')
  })
  it('offers it when the history read works', () => {
    expect(cvAvailability({ loading: false })).toBe('yes')
  })
  it('does not hide it for an unrelated failure the section can explain', () => {
    expect(cvAvailability({ loading: false, error: 'Failed to fetch' })).toBe('yes')
  })
})
