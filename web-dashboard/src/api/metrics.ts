// FastAPI does not yet expose resource metrics. Deliberately return null, never fabricated metrics.
export interface ResourceMetrics { waterPerKg: null; fertilizerPerKg: null; costPerKg: null }
import { apiRequest } from './client'
import { usingMockData } from './farms'
export async function getResourceMetrics(cropSeasonId?: string): Promise<ResourceMetrics> { if (usingMockData || !cropSeasonId) return { waterPerKg: null, fertilizerPerKg: null, costPerKg: null }; const x = await apiRequest<any>(`/v1/crop-seasons/${cropSeasonId}/metrics`); return { waterPerKg: x.water_per_kg, fertilizerPerKg: x.fertilizer_per_kg, costPerKg: x.cost_per_kg } }
