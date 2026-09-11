import { activities, cropSeasons } from '../mocks/data'
import type { Activity, CropSeason } from '../types'
import { apiRequest } from './client'
import { usingMockData } from './farms'
const season = (x: any): CropSeason => ({ id: x.id, plotId: x.plot_id, name: x.season_code, variety: x.variety_name, plantingDate: x.planting_date, harvestDate: x.actual_harvest_date, status: x.status })
const activity = (x: any): Activity => ({ id: x.id, cropSeasonId: '', occurredAt: x.occurred_at, type: x.activity_type, detail: JSON.stringify(x.payload), recorder: x.recorded_by ?? '—', source: x.source })
export async function getCropSeasons(id: string): Promise<CropSeason[]> { return usingMockData ? cropSeasons.filter((x) => x.plotId === id) : (await apiRequest<{ items: any[] }>(`/v1/plots/${id}/crop-seasons`)).items.map(season) }
export async function getCropSeason(id: string): Promise<CropSeason | undefined> { return usingMockData ? cropSeasons.find((x) => x.id === id) : season(await apiRequest<any>(`/v1/crop-seasons/${id}`)) }
export async function getActivities(id: string): Promise<Activity[]> { return usingMockData ? activities.filter((x) => x.cropSeasonId === id) : (await apiRequest<{ items: any[] }>(`/v1/crop-seasons/${id}/activities`)).items.map(activity) }

export interface ProductionBatch { id: string; batchCode: string; name: string | null; status: string; startedOn: string | null; closedOn: string | null }
export async function getProductionBatches(cropSeasonId: string): Promise<ProductionBatch[]> {
  if (usingMockData) return []
  const r = await apiRequest<{ items: any[] }>(`/v1/crop-seasons/${cropSeasonId}/production-batches`)
  return r.items.map((x) => ({ id: x.id, batchCode: x.batch_code, name: x.name ?? null, status: x.status, startedOn: x.started_on ?? null, closedOn: x.closed_on ?? null }))
}
