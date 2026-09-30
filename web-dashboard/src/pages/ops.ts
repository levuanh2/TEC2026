import { useEffect, useState } from 'react'
import { getOrganizationCarbonStatus, type CarbonMissingInput, type CarbonSeasonStatus } from '../api/carbon'
import { getOrganizationPlotsSeasons, listFarms } from '../api/farms'
import { listMrvBatches, listMrvCases } from '../api/mrv'
import { carbonView, type CarbonDisplayState, type CarbonView } from '../carbon/readiness'
import { getEngineInfo } from '../api/engine'
import { label, seasonStatus } from '../vocab'
import type { CropSeason, Farm, Plot } from '../types'

/* The cooperative's work queue, assembled from the endpoints that already
 * exist. There is no "seasons of an organization" route, so this composes
 * farms → seasons, reads every season's readiness + actual Carbon result in
 * ONE organization-wide request (Round 5.1: it used to be two requests per
 * season), and maps MRV cases to seasons through their production batches. Nothing is derived beyond what the server
 * already said: readiness decides what is missing, the Carbon result decides
 * whether a season has one, MRV state is the case's own status.
 */

export type DataState = 'complete' | 'missing' | 'unknown'
/** Kept as an alias of the shared view model's state so no screen invents its own. */
export type CarbonState = CarbonDisplayState

export interface OpsRow {
  seasonId: string
  seasonName: string
  status?: string
  /** Season status in Vietnamese — a raw `active` never reaches a table. */
  statusLabel: string
  farmId: string
  farmName: string
  farmCode?: string
  plotId: string
  /** Plot identity. Without it two seasons of the same farm and season code
   *  render as identical rows, which is exactly what the audit found. */
  plotName?: string
  plotCode?: string
  /** Blocking inputs the farmer can still supply. */
  missing: CarbonMissingInput[]
  /** Blocking inputs no data entry can resolve (unverified factors). */
  limitations: CarbonMissingInput[]
  data: DataState
  carbon: CarbonState
  /** The one readiness answer every Management surface renders. */
  view: CarbonView | null
  carbonPerKg: number | null
  /** Stored result's season total — shown only when a result exists. */
  totalCo2eKg: number | null
  calculatedAt: string | null
  /** The season's own dates, as stored — no inferred deadlines. */
  plantingDate?: string
  harvestDate?: string
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

/** The shape every row starts as, before its per-season detail resolves. */
function baseRow(farm: Farm, season: CropSeason, plot: Plot | undefined,
                 mrvBySeason: Map<string, { caseId: string; caseCode: string; status: string }>): OpsRow {
  return {
    seasonId: season.id, seasonName: season.name, status: season.status,
    statusLabel: seasonStatus(season.status),
    farmId: farm.id, farmName: farm.name, farmCode: farm.code,
    plotId: season.plotId, plotName: plot?.name, plotCode: plot?.code,
    missing: [], limitations: [], data: 'unknown', carbon: 'unknown', view: null,
    carbonPerKg: null, totalCo2eKg: null, calculatedAt: null, mrv: mrvBySeason.get(season.id) ?? null,
    plantingDate: season.plantingDate, harvestDate: season.harvestDate,
  }
}

/** A season's row from its item of the organization-wide Carbon status. */
export function seasonRow(
  base: OpsRow,
  status: CarbonSeasonStatus | undefined,
  efConfigVersion: string | null,
): OpsRow {
  const { seasonId } = base
  if (!status) return { ...base, loading: false, error: 'Không đọc được trạng thái Carbon của vụ này.' }
  const failed = status.readiness_error ?? status.actual_error
  if (failed || !status.readiness) {
    return { ...base, loading: false, error: failed?.message ?? 'Không đọc được trạng thái Carbon của vụ này.' }
  }
  const result = status.actual
  // One decision, taken in one place, for Overview, Seasons, Data gaps,
  // Carbon and the season's own Carbon tab alike.
  const view = carbonView({
    readiness: status.readiness,
    result,
    liveEfConfigVersion: efConfigVersion,
    fixTarget: `/crop-seasons/${seasonId}`,
    resultTarget: `/crop-seasons/${seasonId}/carbon`,
  })
  return {
    ...base,
    loading: false,
    missing: view.userFixableGaps,
    limitations: view.methodologyLimitations,
    // "Đủ dữ liệu" is about what a person can still supply, so a factor
    // limitation never makes a season look incomplete — and a remaining
    // user-fixable gap never lets it look complete.
    data: view.userFixableGaps.length ? 'missing' : 'complete',
    carbon: view.calculationStatus,
    view,
    carbonPerKg: result?.co2e_per_kg ?? null,
    totalCo2eKg: result ? (result.total_co2e_kg ?? result.co2e_total_kg ?? null) : null,
    calculatedAt: result?.calculated_at ?? null,
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
        /* Every season's Carbon state in one request. It needs nothing from
         * the farm→season chain, so it runs beside it; its count of requests
         * does not grow with the number of seasons. */
        const statusWork = getOrganizationCarbonStatus(organizationId)
          .then((body) => ({ items: new Map(body.items.map((i) => [i.crop_season_id, i])), error: null as string | null }))
          .catch((e: unknown) => ({ items: new Map<string, CarbonSeasonStatus>(), error: e instanceof Error ? e.message : 'Không đọc được trạng thái Carbon.' }))
        const engineWork = getEngineInfo()
        // RLS already scopes /v1/farms to what this manager may see.
        const farms = await listFarms()

        /* MRV and the engine's factor-set version depend on nothing in the
         * farm→season chain, so they run beside it instead of in front of it.
         * On the demo tenant this removed a full serial leg from first paint. */
        const mrvBySeason = new Map<string, { caseId: string; caseCode: string; status: string }>()
        const mrvWork = (async () => {
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
        })()

        // Plots come with the seasons, for every farm in ONE request (Round
        // 5.1: it was two per farm): a row without its plot name is a row an
        // officer cannot tell apart.
        const [listing] = await Promise.all([getOrganizationPlotsSeasons(organizationId), mrvWork])
        const byFarm = farms.map((f) => ({ farm: f, seasons: listing.get(f.id)?.seasons ?? [], plots: listing.get(f.id)?.plots ?? [] }))
        const engine = await engineWork
        const efConfigVersion = engine?.efConfigVersion ?? null
        const pairs = byFarm.flatMap(({ farm, seasons, plots }) => {
          const plotById = new Map(plots.map((pl) => [pl.id, pl]))
          return seasons.map((season) => ({ farm, season, plot: plotById.get(season.plotId) }))
        })

        /* The table paints as soon as the seasons are known; Carbon state
         * fills every row at once when the organization-wide status answers. */
        const rows: OpsRow[] = pairs.map(({ farm, season, plot }) => ({
          ...baseRow(farm, season, plot, mrvBySeason), loading: true,
        }))
        let pending = rows.length
        const publish = () => { if (live) setState({ data: { rows: [...rows], farms, pending }, loading: pending > 0, error: null }) }
        publish()
        const status = await statusWork
        for (let i = 0; i < rows.length; i++) {
          rows[i] = status.error
            ? { ...rows[i], loading: false, error: status.error }
            : seasonRow(rows[i], status.items.get(rows[i].seasonId), efConfigVersion)
        }
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
    if (row.carbon === 'stale') {
      out.push({
        id: `${row.seasonId}:stale`, severity: 'medium', row,
        issue: 'Kết quả Carbon đã cũ',
        detail: 'Dữ liệu thay đổi sau lần tính gần nhất — cần tính lại.',
        action: { label: 'Tính lại', to: `/crop-seasons/${row.seasonId}/carbon` },
      })
    }
    if (row.carbon === 'methodology_limited') {
      out.push({
        id: `${row.seasonId}:limited`, severity: 'low', row,
        issue: 'Giới hạn của bộ hệ số',
        detail: row.limitations.map((m) => m.label).join(' · '),
        action: { label: 'Xem', to },
      })
    }
    /* `verified`/`closed` are the only settled `mrv_case_status` values. The
     * previous filter compared against 'approved'/'exported', which are not in
     * that enum at all, so every case looked outstanding for ever. */
    if (row.mrv && row.mrv.status !== 'verified' && row.mrv.status !== 'closed') {
      out.push({
        id: `${row.seasonId}:mrv`, severity: 'medium', row,
        issue: `Hồ sơ MRV ${row.mrv.caseCode} chờ xử lý`,
        detail: `Trạng thái hiện tại: ${label('mrvCaseStatus', row.mrv.status)}.`,
        // There is no review/approve endpoint for an MRV case, so this opens
        // the record instead of promising an approval the API cannot perform.
        action: { label: 'Mở hồ sơ MRV', to: '/mrv' },
      })
    }
  }
  const rank: Record<Severity, number> = { high: 0, medium: 1, low: 2 }
  return out.sort((a, b) => rank[a.severity] - rank[b.severity] || a.row.farmName.localeCompare(b.row.farmName, 'vi'))
}
