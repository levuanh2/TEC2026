// Resource-efficiency metrics. Backend computes every per-kg ratio and aggregate
// (docs/API_FOR_REACT.md §1) — React only displays. null stays null, never 0.
import { apiRequest } from './client'
import { usingMockData } from './farms'

export interface SeasonMetrics {
  yieldKg: number | null
  waterM3: number | null
  fertilizerKg: number | null
  totalCo2eKg: number | null
  waterPerKg: number | null
  fertilizerPerKg: number | null
  co2ePerKg: number | null
  costPerKg: number | null
  completeness: { water: boolean; fertilizer: boolean; cost: boolean; carbon: boolean }
}

/** Kept name for back-compat; now returns the full MetricResponse shape. */
export type ResourceMetrics = SeasonMetrics

const EMPTY: SeasonMetrics = {
  yieldKg: null, waterM3: null, fertilizerKg: null, totalCo2eKg: null,
  waterPerKg: null, fertilizerPerKg: null, co2ePerKg: null, costPerKg: null,
  completeness: { water: false, fertilizer: false, cost: false, carbon: false },
}

const metric = (x: any): SeasonMetrics => ({
  yieldKg: x.yield_kg ?? null,
  waterM3: x.water_m3 ?? null,
  fertilizerKg: x.fertilizer_kg ?? null,
  totalCo2eKg: x.total_co2e_kg ?? null,
  waterPerKg: x.water_per_kg ?? null,
  fertilizerPerKg: x.fertilizer_per_kg ?? null,
  co2ePerKg: x.co2e_per_kg ?? null,
  costPerKg: x.cost_per_kg ?? null,
  completeness: {
    water: Boolean(x.data_completeness?.water),
    fertilizer: Boolean(x.data_completeness?.fertilizer),
    cost: Boolean(x.data_completeness?.cost),
    carbon: Boolean(x.data_completeness?.carbon),
  },
})

export async function getResourceMetrics(cropSeasonId?: string): Promise<SeasonMetrics> {
  if (usingMockData || !cropSeasonId) return EMPTY
  return metric(await apiRequest<any>(`/v1/crop-seasons/${cropSeasonId}/metrics`))
}
