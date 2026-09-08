import { apiRequest } from './client'

export interface Organization {
  id: string; code: string; name: string; organizationType: string
  province?: string; district?: string; commune?: string; isActive: boolean
}
export interface OrganizationSummary {
  organizationId: string; farmCount: number; plotCount: number; cropSeasonCount: number; totalAreaHa: number
  totalYieldKg: number | null; totalCo2eKg: number | null; co2ePerKg: number | null
}
export interface FarmPerformance {
  farmId: string; farmName: string; areaHa: number; yieldKg: number | null; waterPerKg: number | null
  fertilizerPerKg: number | null; co2ePerKg: number | null; costPerKg: number | null
  dataStatus: 'complete' | 'partial' | 'missing'
}

const organization = (x: { id: string; organization_code: string; name: string; organization_type: string; province_name?: string | null; district_name?: string | null; commune_name?: string | null; is_active: boolean }): Organization => ({ id: x.id, code: x.organization_code, name: x.name, organizationType: x.organization_type, province: x.province_name ?? undefined, district: x.district_name ?? undefined, commune: x.commune_name ?? undefined, isActive: x.is_active })
const summary = (x: { organization_id: string; farm_count: number; plot_count: number; crop_season_count: number; total_area_ha: number; total_yield_kg: number | null; total_co2e_kg: number | null; co2e_per_kg: number | null }): OrganizationSummary => ({ organizationId: x.organization_id, farmCount: x.farm_count, plotCount: x.plot_count, cropSeasonCount: x.crop_season_count, totalAreaHa: x.total_area_ha, totalYieldKg: x.total_yield_kg, totalCo2eKg: x.total_co2e_kg, co2ePerKg: x.co2e_per_kg })
const performance = (x: { farm_id: string; farm_name: string; area_ha: number; yield_kg: number | null; water_per_kg: number | null; fertilizer_per_kg: number | null; co2e_per_kg: number | null; cost_per_kg: number | null; data_status: 'complete' | 'partial' | 'missing' }): FarmPerformance => ({ farmId: x.farm_id, farmName: x.farm_name, areaHa: x.area_ha, yieldKg: x.yield_kg, waterPerKg: x.water_per_kg, fertilizerPerKg: x.fertilizer_per_kg, co2ePerKg: x.co2e_per_kg, costPerKg: x.cost_per_kg, dataStatus: x.data_status })

export async function listOrganizations(): Promise<Organization[]> { return (await apiRequest<{ items: Parameters<typeof organization>[0][] }>('/v1/organizations')).items.map(organization) }
export async function getOrganization(id: string): Promise<Organization> { return organization(await apiRequest<Parameters<typeof organization>[0]>(`/v1/organizations/${id}`)) }
export async function getOrganizationSummary(id: string): Promise<OrganizationSummary> { return summary(await apiRequest<Parameters<typeof summary>[0]>(`/v1/organizations/${id}/summary`)) }
export async function getFarmPerformance(id: string): Promise<FarmPerformance[]> { return (await apiRequest<{ items: Parameters<typeof performance>[0][] }>(`/v1/organizations/${id}/farm-performance`)).items.map(performance) }
