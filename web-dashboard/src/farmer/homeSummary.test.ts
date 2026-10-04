import { describe, expect, it } from 'vitest'
import type { ActivitySummary } from '../api/crops'
import type { Activity } from '../types'
import { seasonFacts, seasonFactsFromSummary } from './metricsView'
import { harvestDate, sowingDate } from './seasonDates'

/* Round 5.1: Home no longer downloads the whole journal. Its facts and dates
 * now come from the server's activity summary, and must equal what the old
 * code derived from every record. The summary below is exactly what
 * `activity_summary` computes for these records (see
 * backend/tests/test_round51_activity_summary.py for the server side). */
const act = (id: string, type: string, occurredAt: string, payload: Record<string, unknown>): Activity =>
  ({ id, cropSeasonId: 's', type, occurredAt, detail: JSON.stringify(payload), recorder: '—', source: 'web' }) as Activity

const journal: Activity[] = [
  act('s1', 'seeding', '2026-05-03T01:00:00+00:00', { cost_vnd: '150000' }),
  act('s0', 'seeding', '2026-05-02T01:00:00+00:00', { cost_vnd: null }),
  act('f1', 'fertilizer', '2026-06-01T01:00:00+00:00', { total_cost_vnd: 200000, nitrogen_percent: '46' }),
  act('f2', 'fertilizer', '2026-06-10T01:00:00+00:00', { total_cost_vnd: '' }),
  act('i1', 'irrigation', '2026-06-15T01:00:00+00:00', { total_cost_vnd: '50000.5' }),
  act('h1', 'harvest', '2026-08-20T01:00:00+00:00', { harvested_area_ha: '1.0' }),
  act('h2', 'harvest', '2026-08-25T01:00:00+00:00', { harvested_area_ha: '0.25' }),
]
const summary: ActivitySummary = {
  total: 7,
  countByType: { seeding: 2, fertilizer: 2, irrigation: 1, harvest: 2 },
  costByType: {
    seeding: { records: 2, withCost: 1, recordedVnd: 150000 },
    fertilizer: { records: 2, withCost: 1, recordedVnd: 200000 },
    irrigation: { records: 1, withCost: 1, recordedVnd: 50000.5 },
    harvest: { records: 2, withCost: 0, recordedVnd: 0 },
  },
  harvests: 2, harvestsWithArea: 2, harvestedAreaHa: 1.25, fertilizerHasNutrient: true,
  firstSeedingAt: '2026-05-02T01:00:00+00:00', lastHarvestAt: '2026-08-25T01:00:00+00:00',
}

describe('Home facts from the server summary', () => {
  it.each([1.3, null])('equal the facts derived from the whole journal (plot area %s)', (plotArea) => {
    expect(seasonFactsFromSummary(summary, plotArea)).toEqual(seasonFacts(journal, plotArea))
  })

  it('refuses a partial harvested area exactly like the list path', () => {
    const partial = journal.map((a) => (a.id === 'h2' ? act('h2', 'harvest', a.occurredAt, {}) : a))
    const s = { ...summary, harvestsWithArea: 1, harvestedAreaHa: 1 }
    expect(seasonFactsFromSummary(s, 1.3)).toEqual(seasonFacts(partial, 1.3))
    expect(seasonFactsFromSummary(s, 1.3).harvestedAreaHa).toBeNull()
  })

  it('gives the same sowing and harvest dates as the journal', () => {
    const season = { plantingDate: undefined, harvestDate: undefined, expectedHarvestDate: undefined }
    const journalDates = { firstSeedingAt: summary.firstSeedingAt, lastHarvestAt: summary.lastHarvestAt }
    expect(sowingDate(season, null, journalDates)).toEqual(sowingDate(season, journal))
    expect(harvestDate(season, null, journalDates)).toEqual(harvestDate(season, journal))
  })

  it('with no summary yet, shows nothing rather than guessing', () => {
    expect(seasonFactsFromSummary(null, 1.3)).toEqual(seasonFacts(null, 1.3))
  })
})
