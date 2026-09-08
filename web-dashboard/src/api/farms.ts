import { farms, plots } from '../mocks/data'
import type { Farm, Plot } from '../types'
import { apiRequest } from './client'
// Mock CHỈ bật khi khai báo rõ =true — mặc định (biến rỗng/không set) là dữ liệu thật,
// đúng quy tắc "production/demo mode = VITE_USE_MOCK_DATA=false".
export const usingMockData = import.meta.env.VITE_USE_MOCK_DATA === 'true'
const farm = (x: any): Farm => ({ id: x.id, code: x.farm_code, name: x.farm_name, province: x.province_name, district: x.district_name, commune: x.commune_name, plotCount: x.plot_count })
const plot = (x: any): Plot => ({ id: x.id, farmId: x.farm_id, code: x.plot_code, name: x.name, areaHa: x.area_ha, location: x.latitude == null ? undefined : `${x.latitude}, ${x.longitude}` })
export async function listFarms(): Promise<Farm[]> { return usingMockData ? farms : (await apiRequest<{ items: any[] }>('/v1/farms')).items.map(farm) }
export async function getFarm(id: string): Promise<Farm | undefined> { return usingMockData ? farms.find((x) => x.id === id) : farm(await apiRequest<any>(`/v1/farms/${id}`)) }
export async function getPlotsForFarm(id: string): Promise<Plot[]> { return usingMockData ? plots.filter((x) => x.farmId === id) : (await apiRequest<{ items: any[] }>(`/v1/farms/${id}/plots`)).items.map(plot) }
export async function getPlot(id: string): Promise<Plot | undefined> { return usingMockData ? plots.find((x) => x.id === id) : plot(await apiRequest<any>(`/v1/plots/${id}`)) }
