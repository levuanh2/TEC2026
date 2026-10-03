/* A season's two dates, with where each one comes from.
 *
 * The season record holds what was DECLARED (planting date entered when the
 * season was started, the expected harvest date, and the actual harvest date
 * set when the season ends). The journal holds what HAPPENED (a seeding or a
 * harvest activity). The header used to read only the record, so it said
 * "Chưa ghi nhận" beside a journal that already had both activities.
 *
 * Nothing here writes a date back to the season: a declared date is the user's
 * input and is never overwritten. A journal date is shown as the fact it is.
 */
import { date } from '../format'
import type { Activity, CropSeason } from '../types'
import { localDay } from './activityView'

export type DateSource = 'journal' | 'season' | 'planned' | 'none'

export interface SeasonDate {
  /** dd/MM/yyyy, or null when nothing is recorded. */
  value: string | null
  /** The same day as YYYY-MM-DD. */
  iso: string | null
  source: DateSource
  /** One short qualifier shown beside the value. */
  note: string | null
}

/** A date-only value stays as written; a timestamp becomes the local day it fell on. */
const day = (iso: string) => (/^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso : localDay(new Date(iso)))

/** Journal dates already known without the list (the server's activity
 * summary, Round 5.1): first seeding and last harvest, as timestamps. */
export interface JournalDates { firstSeedingAt?: string | null; lastHarvestAt?: string | null }

function journalDay(activities: Activity[] | null | undefined, type: string, pick: 'first' | 'last'): string | null {
  const days = (activities ?? []).filter((a) => a.type === type && a.occurredAt).map((a) => day(a.occurredAt)).sort()
  if (!days.length) return null
  return pick === 'first' ? days[0] : days[days.length - 1]
}

export function sowingDate(season: Pick<CropSeason, 'plantingDate'>, activities?: Activity[] | null, journal?: JournalDates): SeasonDate {
  const logged = journal ? (journal.firstSeedingAt ? day(journal.firstSeedingAt) : null) : journalDay(activities, 'seeding', 'first')
  const declared = season.plantingDate ? day(season.plantingDate) : null
  if (logged) {
    return {
      value: date(logged), iso: logged, source: 'journal',
      note: declared && declared !== logged ? `theo nhật ký · khai báo ${date(declared)}` : 'theo nhật ký',
    }
  }
  if (declared) return { value: date(declared), iso: declared, source: 'season', note: 'khai báo khi tạo vụ' }
  return { value: null, iso: null, source: 'none', note: null }
}

export function harvestDate(
  season: Pick<CropSeason, 'harvestDate' | 'expectedHarvestDate'>, activities?: Activity[] | null, journal?: JournalDates,
): SeasonDate {
  if (season.harvestDate) return { value: date(season.harvestDate), iso: day(season.harvestDate), source: 'season', note: 'ngày kết thúc vụ' }
  const logged = journal ? (journal.lastHarvestAt ? day(journal.lastHarvestAt) : null) : journalDay(activities, 'harvest', 'last')
  if (logged) return { value: date(logged), iso: logged, source: 'journal', note: 'theo nhật ký' }
  if (season.expectedHarvestDate) {
    const planned = day(season.expectedHarvestDate)
    return { value: date(planned), iso: planned, source: 'planned', note: 'dự kiến' }
  }
  return { value: null, iso: null, source: 'none', note: null }
}
