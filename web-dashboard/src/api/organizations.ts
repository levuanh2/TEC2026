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

// Session-scoped memoization: org identity (name/code/type/province) is
// stable reference data, not a business metric — unlike summary/metrics/
// farm-performance below, which stay uncached because they are live rollups
// that must never look stale (brief Part B §18). This alone removes the
// duplicate `getOrganization` call that both the shell nav header
// (App.tsx's AppShell) and whichever page is showing (Dashboard/Directory/
// Performance) were each issuing for the same organization id on every
// render of that page (brief Part B §20).
const organizationCache = new Map<string, Promise<Organization>>()
export function getOrganization(id: string): Promise<Organization> {
  let cached = organizationCache.get(id)
  if (!cached) {
    cached = apiRequest<Parameters<typeof organization>[0]>(`/v1/organizations/${id}`).then(organization)
    cached.catch(() => organizationCache.delete(id))
    organizationCache.set(id, cached)
  }
  return cached
}
export function clearOrganizationCache(): void { organizationCache.clear() }

export async function getOrganizationSummary(id: string): Promise<OrganizationSummary> { return summary(await apiRequest<Parameters<typeof summary>[0]>(`/v1/organizations/${id}/summary`)) }
export async function getFarmPerformance(id: string): Promise<FarmPerformance[]> { return (await apiRequest<{ items: Parameters<typeof performance>[0][] }>(`/v1/organizations/${id}/farm-performance`)).items.map(performance) }

// Org-level resource-efficiency rollup (MetricResponse). Used for the Dashboard
// "Hiệu suất vùng/HTX" section + the Performance page (brief §5, §11).
export interface OrgMetrics {
  waterPerKg: number | null; fertilizerPerKg: number | null; co2ePerKg: number | null; costPerKg: number | null
  yieldKg: number | null; waterM3: number | null; fertilizerKg: number | null; totalCo2eKg: number | null
  completeness: { water: boolean; fertilizer: boolean; cost: boolean; carbon: boolean }
}
export async function getOrganizationMetrics(id: string): Promise<OrgMetrics> {
  const x = await apiRequest<any>(`/v1/organizations/${id}/metrics`)
  return {
    waterPerKg: x.water_per_kg ?? null, fertilizerPerKg: x.fertilizer_per_kg ?? null,
    co2ePerKg: x.co2e_per_kg ?? null, costPerKg: x.cost_per_kg ?? null,
    yieldKg: x.yield_kg ?? null, waterM3: x.water_m3 ?? null, fertilizerKg: x.fertilizer_kg ?? null, totalCo2eKg: x.total_co2e_kg ?? null,
    completeness: { water: Boolean(x.data_completeness?.water), fertilizer: Boolean(x.data_completeness?.fertilizer), cost: Boolean(x.data_completeness?.cost), carbon: Boolean(x.data_completeness?.carbon) },
  }
}
