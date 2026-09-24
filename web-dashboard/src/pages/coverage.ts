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
 * requests on a 6-season tenant). That is gone; the season count waits for a
 * batch endpoint and the UI says so instead of inventing it. */

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

/** Why one farm has no figure for this metric, in the words of what to record.
 *  Yield is checked first: it is the denominator of every per-kg figure. */
export function missingReason(f: FarmPerformance, key: AggregateKey): string {
  if (f.dataStatus === 'missing') return 'Chưa có vụ nào có dữ liệu'
  if (f.yieldKg == null) return 'Có vụ thiếu sản lượng thu hoạch'
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

/** "Dựa trên 1/3 nông hộ đủ dữ liệu" — always said beside an aggregate. */
export const coverageLine = (c: Coverage) => `Dựa trên ${c.valid}/${c.total} nông hộ đủ dữ liệu`

/** What the page cannot state yet, and why. */
export const SEASON_COVERAGE_PENDING = 'Chưa có dữ liệu tổng hợp — cần endpoint chỉ số theo lô.'
