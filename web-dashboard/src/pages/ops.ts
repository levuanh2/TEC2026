import { useEffect, useState } from 'react'
import { getCarbon, getCarbonReadiness, type CarbonMissingInput } from '../api/carbon'
import { getFarmCropSeasons, listFarms } from '../api/farms'
import { listMrvBatches, listMrvCases } from '../api/mrv'
import type { CropSeason, Farm } from '../types'

/* The cooperative's work queue, assembled from the endpoints that already
 * exist. There is no "seasons of an organization" route, so this composes
 * farms → seasons → per-season readiness/carbon, and maps MRV cases to seasons
 * through their production batches. Nothing is derived beyond what the server
 * already said: readiness decides what is missing, the Carbon result decides
 * whether a season has one, MRV state is the case's own status.
 */

export type DataState = 'complete' | 'missing' | 'unknown'
export type CarbonState = 'calculated' | 'ready' | 'blocked' | 'limited' | 'unknown'

export interface OpsRow {
  seasonId: string
  seasonName: string
  status?: string
  farmId: string
  farmName: string
  farmCode?: string
  plotId: string
  /** Blocking inputs the farmer can still supply. */
  missing: CarbonMissingInput[]
  /** Blocking inputs no data entry can resolve (unverified factors). */
  limitations: CarbonMissingInput[]
  data: DataState
  carbon: CarbonState
  carbonPerKg: number | null
  calculatedAt: string | null
  mrv: { caseId: string; caseCode: string; status: string } | null
  /** Unavailable rows still render — the row says so instead of vanishing. */
  error?: string
  /** This row's per-season detail is still being read. */
  loading?: boolean
}

export interface OpsData {
  rows: OpsRow[]
  farms: Farm[]
  /** Rows still loading their per-season detail. */
  pending: number
}

const CONCURRENCY = 4

async function mapLimited<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length)
  let next = 0
  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, async () => {
      for (;;) {
        const i = next++
        if (i >= items.length) return
        out[i] = await fn(items[i])
      }
    }),
  )
  return out
}

function carbonState(row: { missing: CarbonMissingInput[]; limitations: CarbonMissingInput[]; canCalculate: boolean; hasResult: boolean }): CarbonState {
  if (row.hasResult) return 'calculated'
  if (row.limitations.length) return 'limited'
  if (row.canCalculate) return 'ready'
  if (row.missing.length) return 'blocked'
  return 'unknown'
}

async function seasonRow(farm: Farm, season: CropSeason, mrvBySeason: Map<string, { caseId: string; caseCode: string; status: string }>): Promise<OpsRow> {
  const base: OpsRow = {
    seasonId: season.id, seasonName: season.name, status: season.status,
    farmId: farm.id, farmName: farm.name, farmCode: farm.code, plotId: season.plotId,
    missing: [], limitations: [], data: 'unknown', carbon: 'unknown',
    carbonPerKg: null, calculatedAt: null, mrv: mrvBySeason.get(season.id) ?? null,
  }
  try {
    const readiness = await getCarbonReadiness(season.id)
    const blocking = readiness.missing_inputs.filter((m) => m.blocking)
    const limitations = blocking.filter((m) => m.flow === 'factor_unavailable')
    const missing = blocking.filter((m) => m.flow !== 'factor_unavailable')
    let hasResult = false
    let carbonPerKg: number | null = null
    let calculatedAt: string | null = null
    try {
      const result = await getCarbon(season.id)
      hasResult = true
      carbonPerKg = result.co2e_per_kg ?? null
      calculatedAt = result.calculated_at ?? null
    } catch {
      // No stored calculation is a normal state, not an error.
    }
    return {
      ...base, missing, limitations,
      data: missing.length ? 'missing' : 'complete',
      carbon: carbonState({ missing, limitations, canCalculate: readiness.can_calculate, hasResult }),
      carbonPerKg, calculatedAt,
    }
  } catch (e) {
    return { ...base, error: e instanceof Error ? e.message : 'Không đọc được dữ liệu vụ này.' }
  }
}

export interface OpsState { data: OpsData | null; loading: boolean; error: string | null; reload: () => void }

export function useOperations(organizationId: string | null): OpsState {
  const [state, setState] = useState<{ data: OpsData | null; loading: boolean; error: string | null }>({ data: null, loading: Boolean(organizationId), error: null })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!organizationId) { setState({ data: null, loading: false, error: null }); return }
    let live = true
    setState((s) => ({ ...s, loading: true, error: null }))
    void (async () => {
      try {
        // RLS already scopes /v1/farms to what this manager may see.
        const farms = await listFarms()
        const mrvBySeason = new Map<string, { caseId: string; caseCode: string; status: string }>()
        try {
          const cases = await listMrvCases()
          const forOrg = cases.filter((c) => c.organizationId === organizationId)
          const batchLists = await mapLimited(forOrg, CONCURRENCY, async (c) => ({ c, batches: await listMrvBatches(c.caseId) }))
          for (const { c, batches } of batchLists) {
            for (const b of batches) mrvBySeason.set(b.cropSeasonId, { caseId: c.caseId, caseCode: c.caseCode, status: c.status })
          }
        } catch {
          // MRV is a separate module; its absence must not empty the queue.
        }
        const seasonsByFarm = await mapLimited(farms, CONCURRENCY, async (f) => ({ farm: f, seasons: await getFarmCropSeasons(f.id).catch(() => [] as CropSeason[]) }))
        const pairs = seasonsByFarm.flatMap(({ farm, seasons }) => seasons.map((season) => ({ farm, season })))

        /* Readiness for one season measured 6-8s against hosted Supabase, so a
         * cooperative with several seasons would stare at an empty table for
         * half a minute. Each season's row is published the moment it resolves:
         * the list fills in front of the officer, and the count says how many
         * are still coming. */
        const rows: OpsRow[] = pairs.map(({ farm, season }) => ({
          seasonId: season.id, seasonName: season.name, status: season.status,
          farmId: farm.id, farmName: farm.name, farmCode: farm.code, plotId: season.plotId,
          missing: [], limitations: [], data: 'unknown', carbon: 'unknown',
          carbonPerKg: null, calculatedAt: null, mrv: mrvBySeason.get(season.id) ?? null, loading: true,
        }))
        let pending = rows.length
        const publish = () => { if (live) setState({ data: { rows: [...rows], farms, pending }, loading: pending > 0, error: null }) }
        publish()
        await mapLimited(pairs, CONCURRENCY, async ({ farm, season }, ) => {
          const row = await seasonRow(farm, season, mrvBySeason)
          const at = rows.findIndex((r) => r.seasonId === season.id)
          if (at >= 0) rows[at] = row
          pending -= 1
          publish()
        })
        pending = 0
        publish()
      } catch (e) {
        if (live) setState({ data: null, loading: false, error: e instanceof Error ? e.message : 'Không tải được dữ liệu hợp tác xã.' })
      }
    })()
    return () => { live = false }
  }, [organizationId, tick])

  return { ...state, reload: () => setTick((t) => t + 1) }
}

export type Severity = 'high' | 'medium' | 'low'

export interface Exception {
  id: string
  severity: Severity
  row: OpsRow
  issue: string
  detail: string
  action: { label: string; to: string }
}

/** The queue: what a cooperative officer has to deal with, worst first.
 *
 * Every entry comes from a state the server reported. A season with nothing
 * outstanding never appears — this is a work list, not a report of everything.
 */
export function exceptionsOf(rows: OpsRow[]): Exception[] {
  const out: Exception[] = []
  for (const row of rows) {
    if (row.loading) continue
    const to = `/crop-seasons/${row.seasonId}`
    if (row.error) {
      out.push({ id: `${row.seasonId}:error`, severity: 'medium', row, issue: 'Không đọc được dữ liệu vụ', detail: row.error, action: { label: 'Xem', to } })
      continue
    }
    if (row.missing.length) {
      out.push({
        id: `${row.seasonId}:missing`, severity: 'high', row,
        issue: `Thiếu ${row.missing.length} thông tin để tính phát thải`,
        detail: row.missing.map((m) => m.label).join(' · '),
        action: { label: 'Xử lý', to },
      })
    }
    if (row.carbon === 'ready') {
      out.push({
        id: `${row.seasonId}:ready`, severity: 'medium', row,
        issue: 'Đã đủ dữ liệu, chưa tính Carbon',
        detail: 'Vụ này có thể tính phát thải ngay.',
        action: { label: 'Tính ngay', to },
      })
    }
    if (row.carbon === 'limited') {
      out.push({
        id: `${row.seasonId}:limited`, severity: 'low', row,
        issue: 'Giới hạn của bộ hệ số',
        detail: row.limitations.map((m) => m.label).join(' · '),
        action: { label: 'Xem', to },
      })
    }
    if (row.mrv && row.mrv.status !== 'approved' && row.mrv.status !== 'exported') {
      out.push({
        id: `${row.seasonId}:mrv`, severity: 'medium', row,
        issue: `Hồ sơ MRV ${row.mrv.caseCode} chờ xử lý`,
        detail: `Trạng thái hiện tại: ${row.mrv.status}.`,
        action: { label: 'Duyệt MRV', to: '/mrv' },
      })
    }
  }
  const rank: Record<Severity, number> = { high: 0, medium: 1, low: 2 }
  return out.sort((a, b) => rank[a.severity] - rank[b.severity] || a.row.farmName.localeCompare(b.row.farmName, 'vi'))
}
