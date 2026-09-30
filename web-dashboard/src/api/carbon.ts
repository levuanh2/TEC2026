import { apiRequest } from './client'
export type Scenario = 'as_recorded' | 'awd' | 'continuous_flooding'
export interface CarbonBreakdown { source: string; gas?: string; co2e_kg: number; [key: string]: unknown }
/** `actual` = the season's operational result (`as_recorded`); `scenario` = a
 * simulation (AWD / continuous flooding) kept for comparison only. */
export type CalculationKind = 'actual' | 'scenario'
export interface CarbonResult { calculation_id?: string | null; crop_season_id: string; water_regime_scenario?: Scenario; scenario?: Scenario; calculation_kind?: CalculationKind; total_co2e_kg: number; co2e_total_kg?: number; co2e_per_kg: number | null; ef_config_version?: string | null; engine_version?: string; input_hash?: string; calculated_at?: string; breakdown: CarbonBreakdown[]; warnings: string[]; [key: string]: unknown }
/** The stored result of ONE scenario. Defaults to the actual (`as_recorded`)
 * result and always names the scenario on the wire: "latest calculation of any
 * kind" let a simulation computed later replace the season's actual result. */
export const getCarbon = (id: string, scenario: Scenario = 'as_recorded') =>
  apiRequest<CarbonResult>(`/v1/crop-seasons/${id}/carbon?scenario=${scenario}`)
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
export interface CarbonReadiness {
  can_calculate: boolean; blocking_count: number; missing_inputs: CarbonMissingInput[]
  /** Fingerprint of the Carbon inputs as they stand now: the `input_hash` the
   * engine would store for an actual calculation. Costs and notes are not in it. */
  input_hash?: string | null
  ef_config_version?: string | null
}
export const getCarbonReadiness = (id: string) => apiRequest<CarbonReadiness>(`/v1/crop-seasons/${id}/carbon/readiness`)

export interface CarbonStatusError { code: string; message: string }
/** One season of an organization's Carbon status: exactly what the per-season
 * readiness and (actual) result endpoints return, or why a part is missing. */
export interface CarbonSeasonStatus {
  crop_season_id: string
  readiness: CarbonReadiness | null
  readiness_error: CarbonStatusError | null
  /** The season's ACTUAL result; null when it has none yet. */
  actual: CarbonResult | null
  actual_error: CarbonStatusError | null
}
/** Readiness + actual result of every season of the organization the caller
 * may read, in ONE request — instead of two requests per season. */
export const getOrganizationCarbonStatus = (organizationId: string) =>
  apiRequest<{ organization_id: string; items: CarbonSeasonStatus[] }>(`/v1/organizations/${organizationId}/carbon-status`)
