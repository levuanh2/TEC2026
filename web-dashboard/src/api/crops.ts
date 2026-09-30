import { activities, cropSeasons } from '../mocks/data'
import type { Activity, CropSeason } from '../types'
import { ApiError, apiRequest } from './client'
import { usingMockData } from './farms'
const season = (x: any): CropSeason => ({ id: x.id, plotId: x.plot_id, name: x.season_code, variety: x.variety_name, plantingDate: x.planting_date, harvestDate: x.actual_harvest_date, expectedHarvestDate: x.expected_harvest_date ?? undefined, status: x.status, ipccWaterRegime: x.ipcc_water_regime ?? null, preSeasonWaterRegime: x.pre_season_water_regime ?? null, cultivationDays: x.cultivation_days ?? null })
const activity = (x: any): Activity => ({ id: x.id, cropSeasonId: '', occurredAt: x.occurred_at, type: x.activity_type, detail: JSON.stringify(x.payload), recorder: x.recorded_by ?? '—', source: x.source })
export async function getCropSeasons(id: string): Promise<CropSeason[]> { return usingMockData ? cropSeasons.filter((x) => x.plotId === id) : (await apiRequest<{ items: any[] }>(`/v1/plots/${id}/crop-seasons`)).items.map(season) }
export async function getCropSeason(id: string): Promise<CropSeason | undefined> { return usingMockData ? cropSeasons.find((x) => x.id === id) : season(await apiRequest<any>(`/v1/crop-seasons/${id}`)) }
/** Every activity of the season. The endpoint is paginated (default 20, max
 * 100 per page, `has_more`); reading only the first page silently dropped
 * everything past the newest 20 — found in Round 5.1 device UAT, where a season
 * with 27 records showed 20 on both Farmer and Management. */
export const ACTIVITY_PAGE_SIZE = 100
/** Upper bound on pages read for one season (5 000 records). Home and the
 * season pages summarize the WHOLE season (record count, costs, harvested
 * area, sowing/harvest dates), so they cannot stop at the newest records; the
 * number of requests is ceil(records / 100) and never unbounded. Past the
 * bound the read FAILS visibly instead of silently showing a partial season. */
export const ACTIVITY_MAX_PAGES = 50
export async function getActivities(id: string): Promise<Activity[]> {
  if (usingMockData) return activities.filter((x) => x.cropSeasonId === id)
  const items: any[] = []
  for (let page = 1; ; page++) {
    const body = await apiRequest<{ items: any[]; has_more?: boolean }>(`/v1/crop-seasons/${id}/activities?page=${page}&page_size=${ACTIVITY_PAGE_SIZE}`)
    items.push(...body.items)
    if (!body.has_more || !body.items.length) break
    if (page >= ACTIVITY_MAX_PAGES) throw new Error(`Vụ này có hơn ${ACTIVITY_PAGE_SIZE * ACTIVITY_MAX_PAGES} bản ghi — không hiển thị một phần để tránh số liệu sai.`)
  }
  return items.map(activity)
}

/**
 * Record the season's IPCC methodology inputs.
 *
 * Only the keys passed are sent, because the backend distinguishes an absent
 * field (keep what is stored) from an explicit null (clear it). Carbon is never
 * computed here — this only supplies inputs the engine reads server-side.
 */
export async function updateSeasonMethodology(
  cropSeasonId: string,
  patch: Partial<Pick<CropSeason, 'ipccWaterRegime' | 'preSeasonWaterRegime' | 'cultivationDays'>>,
): Promise<CropSeason> {
  const body: Record<string, unknown> = {}
  if ('ipccWaterRegime' in patch) body.ipcc_water_regime = patch.ipccWaterRegime ?? null
  if ('preSeasonWaterRegime' in patch) body.pre_season_water_regime = patch.preSeasonWaterRegime ?? null
  if ('cultivationDays' in patch) body.cultivation_days = patch.cultivationDays ?? null
  return season(await apiRequest<any>(`/v1/crop-seasons/${cropSeasonId}/methodology`, { method: 'PATCH', body: JSON.stringify(body) }))
}

export interface ProductionBatch { id: string; batchCode: string; name: string | null; status: string; startedOn: string | null; closedOn: string | null }
export async function getProductionBatches(cropSeasonId: string): Promise<ProductionBatch[]> {
  if (usingMockData) return []
  const r = await apiRequest<{ items: any[] }>(`/v1/crop-seasons/${cropSeasonId}/production-batches`)
  return r.items.map((x) => ({ id: x.id, batchCode: x.batch_code, name: x.name ?? null, status: x.status, startedOn: x.started_on ?? null, closedOn: x.closed_on ?? null }))
}

/** What a person fills in to start a season. Everything else -- crop type,
 * status, the default production batch -- is decided by the server. */
export interface StartSeasonInput { seasonCode: string; variety?: string | null; plantingDate?: string | null; expectedHarvestDate?: string | null }
export interface StartedSeason { season: CropSeason; defaultBatchId: string; replay: boolean }

/**
 * Start a crop season on a plot: `POST /v1/plots/{plotId}/crop-seasons`.
 *
 * One call. The server creates the season AND its default production batch in
 * one transaction, so the season returned here can take activities at once --
 * the client never creates the batch. Farmer Web and Management Web share it.
 */
export async function startCropSeason(plotId: string, input: StartSeasonInput): Promise<StartedSeason> {
  const body = {
    season_code: input.seasonCode.trim(),
    variety_name: input.variety?.trim() || null,
    planting_date: input.plantingDate || null,
    expected_harvest_date: input.expectedHarvestDate || null,
  }
  if (usingMockData) {
    const clash = cropSeasons.find((s) => s.plotId === plotId && s.name === body.season_code)
    if (clash) throw new ApiError(409, 'season_code_exists', 'Thửa này đã có một vụ với mã này. Hãy dùng mã vụ khác.')
    if (cropSeasons.some((s) => s.plotId === plotId && s.status === 'active')) {
      throw new ApiError(409, 'active_season_exists', 'Thửa này đang có một vụ đang canh tác. Kết thúc vụ đó trước khi bắt đầu vụ mới.')
    }
    const created: CropSeason = { id: `crop-mock-${cropSeasons.length + 1}`, plotId, name: body.season_code, variety: body.variety_name ?? undefined, plantingDate: body.planting_date ?? undefined, status: 'active', ipccWaterRegime: null, preSeasonWaterRegime: null, cultivationDays: null }
    cropSeasons.push(created)
    return { season: created, defaultBatchId: `batch-mock-${created.id}`, replay: false }
  }
  const x = await apiRequest<any>(`/v1/plots/${plotId}/crop-seasons`, { method: 'POST', body: JSON.stringify(body) })
  return { season: season(x), defaultBatchId: x.default_production_batch_id, replay: Boolean(x.idempotent_replay) }
}

/** "Kết thúc vụ": `PATCH /v1/crop-seasons/{id}/status`. The server decides
 * which moves are legal (never a reopening); afterwards every client -- Web
 * and the Flutter app -- is refused new journal writes for this season. */
export async function endCropSeason(cropSeasonId: string, actualHarvestDate?: string | null): Promise<CropSeason> {
  if (usingMockData) {
    const s = cropSeasons.find((x) => x.id === cropSeasonId)
    if (!s) throw new ApiError(404, 'not_found', 'Không tìm thấy vụ.')
    if (s.status !== 'active') throw new ApiError(409, 'illegal_crop_season_transition', 'Vụ đã kết thúc.')
    s.status = 'harvested'
    if (actualHarvestDate) s.harvestDate = actualHarvestDate
    return s
  }
  const body: Record<string, unknown> = { status: 'harvested' }
  if (actualHarvestDate) body.actual_harvest_date = actualHarvestDate
  return season(await apiRequest<any>(`/v1/crop-seasons/${cropSeasonId}/status`, { method: 'PATCH', body: JSON.stringify(body) }))
}

export function endSeasonErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 'illegal_crop_season_transition') return 'Vụ này đã kết thúc; vụ đã kết thúc không mở lại được.'
    if (err.status === 404) return 'Bạn không có quyền kết thúc vụ này.'
    if (err.status === 422) return 'Ngày thu hoạch chưa hợp lệ (không được trước ngày gieo sạ).'
    if (err.code === 'offline') return 'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.'
  }
  return 'Chưa kết thúc được vụ. Vui lòng thử lại.'
}
