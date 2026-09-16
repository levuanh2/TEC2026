// Exactly the backend `organization_role` values that choose a shell — no aliases (B2).
export type Role = 'farmer' | 'cooperative_manager' | 'enterprise_viewer' | 'regulator'
export interface Farm { id: string; code: string; name: string; province?: string; district?: string; commune?: string; plotCount: number; areaHa?: number }
export interface Plot { id: string; farmId: string; code: string; name: string; areaHa?: number; location?: string }
/** IPCC water regime during the season — `public.ipcc_water_regime` (Table 5.12). */
export type IpccWaterRegime =
  | 'irrigated_continuous_flooding' | 'irrigated_single_drainage' | 'irrigated_multiple_drainage'
  | 'rainfed_regular' | 'rainfed_drought_prone' | 'deep_water' | 'upland'
/** IPCC pre-season water regime — `public.ipcc_pre_season_regime` (Table 5.13). */
export type IpccPreSeasonRegime =
  | 'non_flooded_pre_season_lt_180d' | 'non_flooded_pre_season_gt_180d'
  | 'flooded_pre_season_gt_30d' | 'non_flooded_pre_season_gt_365d'

export interface CropSeason { id: string; plotId: string; name: string; variety?: string; plantingDate?: string; harvestDate?: string; status?: string; totalYieldKg?: number | null;
  /** Carbon methodology inputs. `null` = chưa ghi nhận — never defaulted client-side. */
  ipccWaterRegime?: IpccWaterRegime | null; preSeasonWaterRegime?: IpccPreSeasonRegime | null; cultivationDays?: number | null }
export interface Activity { id: string; cropSeasonId: string; occurredAt: string; type: string; detail: string; recorder: string; source: string }
