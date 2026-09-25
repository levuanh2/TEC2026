import type { FarmPerformance } from '../api/organizations'

/* Which farms stand behind a cooperative aggregate (Round 4.3 gate).
 *
 * `/organizations/{id}/metrics` returns one figure per metric, and null as soon
 * as any season lacks the data. The Performance page already loads
 * `/organizations/{id}/farm-performance`, whose per-farm figure is null under
 * the same rule — a farm has a water/kg figure only when every one of its
 * seasons does. So coverage *per farm* is exact from a payload the page
 * already holds, with no extra request.
 *
 * Coverage *per season* is not derivable from anything the page loads. An
 * earlier draft fetched every season's `/metrics` to get it (N+1: 5 → 18
 * requests on a 6-season tenant). That is gone; the UI says coverage is
 * counted per farm and does not invent a per-season count (a batch per-season
 * figure is a backend request, recorded in docs/WEB_UX_REDESIGN_ROUND4_4.md,
 * never UI copy). */

export type AggregateKey = 'water' | 'fertilizer' | 'cost' | 'carbon'

export interface MissingFarm { farm: FarmPerformance; reason: string }

export interface Coverage {
  /** Farms in scope. */
  total: number
  /** Farms whose own per-kg figure exists for this metric. */
  valid: number
  missing: MissingFarm[]
}

const PER_KG: Record<AggregateKey, keyof FarmPerformance> = {
  water: 'waterPerKg', fertilizer: 'fertilizerPerKg', cost: 'costPerKg', carbon: 'co2ePerKg',
}

/** What the farm-performance payload can truthfully say about one farm's
 *  harvest (Round 4.4).
 *
 *  The server's per-farm `yield_kg` is the sum over the farm's seasons only
 *  when *every* season has a harvest, and null as soon as one does not
 *  (backend `farm_performance`). So null does not mean "nothing harvested": a
 *  farm with 5 200 kg on one season and no harvest on another is null too.
 *  The payload has no recorded-so-far subtotal and no season count, so the
 *  partial state is named without a figure rather than guessed:
 *  - `recorded`   every season has a harvest; `yieldKg` is their total.
 *  - `incomplete` at least one season lacks a harvest; whether another has
 *                 one is not in the payload.
 *  - `none`       the farm has no season, so no harvest at all. */
export type HarvestState = 'recorded' | 'incomplete' | 'none'
export function harvestState(f: FarmPerformance): HarvestState {
  if (f.yieldKg != null) return 'recorded'
  return f.dataStatus === 'missing' ? 'none' : 'incomplete'
}
export const HARVEST_COPY: Record<Exclude<HarvestState, 'recorded'>, string> = {
  none: 'Chưa có sản lượng thu hoạch',
  incomplete: 'Có vụ chưa ghi sản lượng thu hoạch',
}

/** Why one farm has no figure for this metric, in the words of what to record.
 *  Yield is checked first: it is the denominator of every per-kg figure. */
export function missingReason(f: FarmPerformance, key: AggregateKey): string {
  if (f.dataStatus === 'missing') return 'Chưa có vụ mùa nào'
  if (f.yieldKg == null) return HARVEST_COPY.incomplete
  switch (key) {
    case 'water': return 'Có vụ thiếu lượng nước tưới'
    case 'fertilizer': return 'Có vụ thiếu khối lượng phân bón'
    case 'cost': return 'Có vụ còn hoạt động chưa ghi chi phí'
    case 'carbon': return 'Có vụ chưa có kết quả Carbon'
  }
}

export function coverageOf(farms: FarmPerformance[], key: AggregateKey): Coverage {
  const missing: MissingFarm[] = []
  let valid = 0
  for (const farm of farms) {
    if (farm[PER_KG[key]] != null) valid += 1
    else missing.push({ farm, reason: missingReason(farm, key) })
  }
  return { total: farms.length, valid, missing }
}

/** One sentence for an aggregate's state and coverage (Round 4.4). It
 *  replaces a badge, a placeholder value and a coverage line that said the
 *  same thing three times. `0/3` is coverage, not a score. */
export function coverageSentence(c: Coverage, published: boolean): string {
  if (published) return `Tính trên ${c.valid}/${c.total} nông hộ đủ dữ liệu.`
  const lead = 'Chưa công bố chỉ số toàn HTX'
  if (c.total === 0) return `${lead} — HTX chưa có nông hộ nào.`
  if (c.valid === 0) return `${lead} — ${c.total}/${c.total} nông hộ còn thiếu dữ liệu.`
  return `${lead} — mới có ${c.valid}/${c.total} nông hộ đủ dữ liệu.`
}

/** Why a cooperative figure may be withheld. */
export const PUBLISH_RULE = 'Chỉ công bố khi mọi vụ của mọi nông hộ đủ dữ liệu.'

/** What the coverage count is, and what it is not. */
export const COVERAGE_BASIS = 'Tính theo nông hộ; chưa có tổng hợp chi tiết theo từng vụ.'
