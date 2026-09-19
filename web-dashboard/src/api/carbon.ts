import { apiRequest } from './client'
export type Scenario = 'as_recorded' | 'awd' | 'continuous_flooding'
export interface CarbonBreakdown { source: string; gas?: string; co2e_kg: number; [key: string]: unknown }
export interface CarbonResult { calculation_id?: string | null; crop_season_id: string; water_regime_scenario?: Scenario; scenario?: Scenario; total_co2e_kg: number; co2e_total_kg?: number; co2e_per_kg: number | null; ef_config_version?: string; engine_version?: string; calculated_at?: string; breakdown: CarbonBreakdown[]; warnings: string[]; [key: string]: unknown }
export const getCarbon = (id: string, scenario?: Scenario) => apiRequest<CarbonResult>(`/v1/crop-seasons/${id}/carbon${scenario ? `?scenario=${scenario}` : ''}`)
export const calculateCarbon = (crop_season_id: string, water_regime_scenario: Scenario) => apiRequest<CarbonResult>('/v1/carbon/calculate', { method: 'POST', body: JSON.stringify({ crop_season_id, water_regime_scenario }) })

/** The stored activity record an issue is about, so the client can open it. */
export interface CarbonMissingRecord { activity_id: string; occurred_on: string | null; label: string | null }

/** One Carbon input the season still lacks. Derived server-side from the same
 * activity data the engine consumes — the client holds no methodology of its own. */
export interface CarbonMissingInput {
  code: string
  label: string
  detail: string
  /** Where the user supplies it. The client routes on this; it does not decide it.
   * `factor_unavailable` is a limitation of the factor set, never a form to fill. */
  flow: 'carbon_methodology' | 'activity' | 'plot' | 'factor_unavailable'
  activity_type: string | null
  /** false = the total is still computable, only the per-kg intensity is not. */
  blocking: boolean
  /** The exact records to open, for activity-level issues. */
  records?: CarbonMissingRecord[]
}
export interface CarbonReadiness { can_calculate: boolean; blocking_count: number; missing_inputs: CarbonMissingInput[] }
export const getCarbonReadiness = (id: string) => apiRequest<CarbonReadiness>(`/v1/crop-seasons/${id}/carbon/readiness`)
