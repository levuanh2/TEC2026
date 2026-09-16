import { activities, cropSeasons } from '../mocks/data'
import type { Activity, CropSeason } from '../types'
import { apiRequest } from './client'
import { usingMockData } from './farms'
const season = (x: any): CropSeason => ({ id: x.id, plotId: x.plot_id, name: x.season_code, variety: x.variety_name, plantingDate: x.planting_date, harvestDate: x.actual_harvest_date, status: x.status, ipccWaterRegime: x.ipcc_water_regime ?? null, preSeasonWaterRegime: x.pre_season_water_regime ?? null, cultivationDays: x.cultivation_days ?? null })
const activity = (x: any): Activity => ({ id: x.id, cropSeasonId: '', occurredAt: x.occurred_at, type: x.activity_type, detail: JSON.stringify(x.payload), recorder: x.recorded_by ?? '—', source: x.source })
export async function getCropSeasons(id: string): Promise<CropSeason[]> { return usingMockData ? cropSeasons.filter((x) => x.plotId === id) : (await apiRequest<{ items: any[] }>(`/v1/plots/${id}/crop-seasons`)).items.map(season) }
export async function getCropSeason(id: string): Promise<CropSeason | undefined> { return usingMockData ? cropSeasons.find((x) => x.id === id) : season(await apiRequest<any>(`/v1/crop-seasons/${id}`)) }
export async function getActivities(id: string): Promise<Activity[]> { return usingMockData ? activities.filter((x) => x.cropSeasonId === id) : (await apiRequest<{ items: any[] }>(`/v1/crop-seasons/${id}/activities`)).items.map(activity) }

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
