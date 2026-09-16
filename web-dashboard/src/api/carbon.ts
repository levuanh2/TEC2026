import { apiRequest } from './client'
export type Scenario = 'as_recorded' | 'awd' | 'continuous_flooding'
export interface CarbonBreakdown { source: string; gas?: string; co2e_kg: number; [key: string]: unknown }
export interface CarbonResult { calculation_id?: string | null; crop_season_id: string; water_regime_scenario?: Scenario; scenario?: Scenario; total_co2e_kg: number; co2e_total_kg?: number; co2e_per_kg: number | null; ef_config_version?: string; engine_version?: string; calculated_at?: string; breakdown: CarbonBreakdown[]; warnings: string[]; [key: string]: unknown }
export const getCarbon = (id: string, scenario?: Scenario) => apiRequest<CarbonResult>(`/v1/crop-seasons/${id}/carbon${scenario ? `?scenario=${scenario}` : ''}`)
export const calculateCarbon = (crop_season_id: string, water_regime_scenario: Scenario) => apiRequest<CarbonResult>('/v1/carbon/calculate', { method: 'POST', body: JSON.stringify({ crop_season_id, water_regime_scenario }) })

/** One Carbon input the season still lacks. Derived server-side from the same
 * activity data the engine consumes — the client holds no methodology of its own. */
export interface CarbonMissingInput {
  code: string
  label: string
  detail: string
  /** Where the user supplies it. The client routes on this; it does not decide it. */
  flow: 'carbon_methodology' | 'activity' | 'plot'
  activity_type: string | null
  /** false = the total is still computable, only the per-kg intensity is not. */
  blocking: boolean
}
export interface CarbonReadiness { can_calculate: boolean; blocking_count: number; missing_inputs: CarbonMissingInput[] }
export const getCarbonReadiness = (id: string) => apiRequest<CarbonReadiness>(`/v1/crop-seasons/${id}/carbon/readiness`)
