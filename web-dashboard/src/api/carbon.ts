import { apiRequest } from './client'
export type Scenario = 'as_recorded' | 'awd' | 'continuous_flooding'
export interface CarbonBreakdown { source: string; gas?: string; co2e_kg: number; [key: string]: unknown }
export interface CarbonResult { calculation_id?: string | null; crop_season_id: string; water_regime_scenario?: Scenario; scenario?: Scenario; total_co2e_kg: number; co2e_total_kg?: number; co2e_per_kg: number | null; ef_config_version?: string; engine_version?: string; calculated_at?: string; breakdown: CarbonBreakdown[]; warnings: string[]; [key: string]: unknown }
export const getCarbon = (id: string, scenario?: Scenario) => apiRequest<CarbonResult>(`/v1/crop-seasons/${id}/carbon${scenario ? `?scenario=${scenario}` : ''}`)
export const calculateCarbon = (crop_season_id: string, water_regime_scenario: Scenario) => apiRequest<CarbonResult>('/v1/carbon/calculate', { method: 'POST', body: JSON.stringify({ crop_season_id, water_regime_scenario }) })
