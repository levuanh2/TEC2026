import { farms, plots, cropSeasons } from '../mocks/data'
import type { CropSeason, Farm, Plot } from '../types'
import { apiRequest } from './client'
import type { SeasonMetrics } from './metrics'
// Mock CHỈ bật khi khai báo rõ =true — mặc định (biến rỗng/không set) là dữ liệu thật,
// đúng quy tắc "production/demo mode = VITE_USE_MOCK_DATA=false".
export const usingMockData = import.meta.env.VITE_USE_MOCK_DATA === 'true'
const farm = (x: any): Farm => ({ id: x.id, code: x.farm_code, name: x.farm_name, province: x.province_name, district: x.district_name, commune: x.commune_name, plotCount: x.plot_count })
const plot = (x: any): Plot => ({ id: x.id, farmId: x.farm_id, code: x.plot_code, name: x.name, areaHa: x.area_ha, location: x.latitude == null ? undefined : `${x.latitude}, ${x.longitude}` })
export async function listFarms(): Promise<Farm[]> { return usingMockData ? farms : (await apiRequest<{ items: any[] }>('/v1/farms')).items.map(farm) }
export async function getFarm(id: string): Promise<Farm | undefined> { return usingMockData ? farms.find((x) => x.id === id) : farm(await apiRequest<any>(`/v1/farms/${id}`)) }
export async function getPlotsForFarm(id: string): Promise<Plot[]> { return usingMockData ? plots.filter((x) => x.farmId === id) : (await apiRequest<{ items: any[] }>(`/v1/farms/${id}/plots`)).items.map(plot) }
export async function getPlot(id: string): Promise<Plot | undefined> { return usingMockData ? plots.find((x) => x.id === id) : plot(await apiRequest<any>(`/v1/plots/${id}`)) }

// --- Farm-level rollups (brief §7 "hiệu suất riêng 1 farm", §22 no client math) ---
const farmSeason = (x: any): CropSeason => ({ id: x.id, plotId: x.plot_id, name: x.season_code, variety: x.variety_name, plantingDate: x.planting_date, harvestDate: x.actual_harvest_date, status: x.status })

export async function getFarmCropSeasons(farmId: string): Promise<CropSeason[]> {
  if (usingMockData) { const ids = plots.filter((p) => p.farmId === farmId).map((p) => p.id); return cropSeasons.filter((s) => ids.includes(s.plotId)) }
  return (await apiRequest<{ items: any[] }>(`/v1/farms/${farmId}/crop-seasons`)).items.map(farmSeason)
}

export async function getFarmMetrics(farmId: string): Promise<SeasonMetrics | null> {
  if (usingMockData) return null
  const x = await apiRequest<any>(`/v1/farms/${farmId}/metrics`)
  return {
    yieldKg: x.yield_kg ?? null, waterM3: x.water_m3 ?? null, fertilizerKg: x.fertilizer_kg ?? null,
    totalCo2eKg: x.total_co2e_kg ?? null, waterPerKg: x.water_per_kg ?? null, fertilizerPerKg: x.fertilizer_per_kg ?? null,
    co2ePerKg: x.co2e_per_kg ?? null, costPerKg: x.cost_per_kg ?? null,
    completeness: { water: Boolean(x.data_completeness?.water), fertilizer: Boolean(x.data_completeness?.fertilizer), cost: Boolean(x.data_completeness?.cost), carbon: Boolean(x.data_completeness?.carbon) },
  }
}
