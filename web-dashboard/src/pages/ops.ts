import { useMemo } from 'react'
import { getOrganizationCarbonStatus, type CarbonMissingInput, type CarbonSeasonStatus } from '../api/carbon'
import { getOrganizationPlotsSeasons, listFarms } from '../api/farms'
import { getOrganizationMrvBatches } from '../api/mrv'
import { carbonView, type CarbonDisplayState, type CarbonView } from '../carbon/readiness'
import { getEngineInfo } from '../api/engine'
import { label, seasonStatus } from '../vocab'
import { useApiQuery } from '../query/hooks'
import { keys, METADATA_STALE_MS } from '../query/client'
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

/** The shape every row starts as, before its per-season detail resolves. */
function baseRow(farm: Farm, season: CropSeason, plot: Plot | undefined,
                 mrvBySeason: Map<string, MrvLink>): OpsRow {
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

export interface SourceState {
  /** Still reading, with nothing to show yet. */
  loading: boolean
  /** The read failed and there is nothing to show from it. */
  error: string | null
}

export interface OpsState {
  data: OpsData | null
  /** True until every row is final (seasons listed AND Carbon state known). */
  loading: boolean
  /** The season listing itself could not be read — there is no table. */
  error: string | null
  reload: () => void
  /** Each source reports on its own, so a slow or failed Carbon read never
   *  holds the season list, and a missing MRV read is never shown as zero. */
  seasons: SourceState
  carbon: SourceState & { failedSeasons: number }
  mrv: SourceState
  /** A background refresh is running over data already on screen. */
  refreshing: boolean
  /** The latest refresh failed; what is on screen is from `updatedAt`. */
  stale: { error: string; updatedAt: number } | null
}

type MrvLink = { caseId: string; caseCode: string; status: string }

/**
 * The cooperative's work queue, from four organisation-wide reads held in the
 * shared query cache: farms, plots+seasons, every season's Carbon state, MRV
 * cases with their batches. Dashboard, Vụ mùa, Dữ liệu thiếu and Carbon all
 * read the SAME cache entries, so moving between them costs no request while
 * the data is fresh (45 s) and shows the cached rows at once while a stale
 * entry refreshes. The request count stays fixed at four (plus the engine
 * version, read once) whatever the number of seasons.
 */
export function useOperations(organizationId: string | null): OpsState {
  const enabled = Boolean(organizationId)
  const org = organizationId ?? ''
  // RLS already scopes /v1/farms to what this manager may see.
  const farms = useApiQuery(keys.farms(), () => listFarms(), { enabled })
  const listing = useApiQuery(keys.org(org, 'plots-seasons'), () => getOrganizationPlotsSeasons(org), { enabled })
  // Every season's readiness + actual result in ONE request (Round 5.1).
  const status = useApiQuery(keys.org(org, 'carbon-status'), () => getOrganizationCarbonStatus(org), { enabled })
  const mrv = useApiQuery(keys.org(org, 'mrv-batches'), () => getOrganizationMrvBatches(org), { enabled })
  const engine = useApiQuery(keys.engine(), () => getEngineInfo(), { enabled, staleTime: METADATA_STALE_MS })

  const composed = useMemo(() => {
    if (!farms.data || !listing.data) return null
    const mrvBySeason = new Map<string, MrvLink>()
    for (const { batches, ...c } of mrv.data ?? []) {
      for (const b of batches) mrvBySeason.set(b.cropSeasonId, { caseId: c.caseId, caseCode: c.caseCode, status: c.status })
    }
    const statusItems = status.data ? new Map(status.data.items.map((i) => [i.crop_season_id, i])) : null
    const engineKnown = engine.data !== undefined || Boolean(engine.error)
    const efConfigVersion = engine.data?.efConfigVersion ?? null
    const rows: OpsRow[] = []
    for (const farm of farms.data) {
      const own = listing.data.get(farm.id)
      const plotById = new Map((own?.plots ?? []).map((pl) => [pl.id, pl]))
      for (const season of own?.seasons ?? []) {
        const base = baseRow(farm, season, plotById.get(season.plotId), mrvBySeason)
        if (statusItems && engineKnown) rows.push(seasonRow(base, statusItems.get(season.id), efConfigVersion))
        else if (status.error) rows.push({ ...base, loading: false, error: status.error })
        else rows.push({ ...base, loading: true })
      }
    }
    return { rows, farms: farms.data, pending: rows.filter((r) => r.loading).length }
  }, [farms.data, listing.data, status.data, status.error, mrv.data, engine.data, engine.error])

  const seasonsError = farms.error ?? listing.error ?? null
  const all = [farms, listing, status, mrv]
  const failing = all.find((q) => q.refreshError)
  const failedSeasons = composed ? composed.rows.filter((r) => r.error).length : 0
  return {
    data: composed,
    loading: enabled && !seasonsError && (!composed || composed.pending > 0),
    error: enabled ? seasonsError : null,
    reload: () => { for (const q of all) q.reload() },
    seasons: { loading: enabled && !composed && !seasonsError, error: seasonsError },
    carbon: { loading: enabled && !status.data && !status.error, error: status.error ?? null, failedSeasons },
    mrv: { loading: enabled && !mrv.data && !mrv.error, error: mrv.error ?? null },
    refreshing: all.some((q) => q.refreshing),
    stale: failing?.refreshError ? { error: failing.refreshError, updatedAt: failing.updatedAt } : null,
  }
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
