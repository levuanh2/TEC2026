export type Role = 'farmer' | 'cooperative_manager' | 'enterprise' | 'regulator'
export interface Farm { id: string; code: string; name: string; province?: string; district?: string; commune?: string; plotCount: number; areaHa?: number }
export interface Plot { id: string; farmId: string; code: string; name: string; areaHa?: number; location?: string }
export interface CropSeason { id: string; plotId: string; name: string; variety?: string; plantingDate?: string; harvestDate?: string; status?: string; totalYieldKg?: number | null }
export interface Activity { id: string; cropSeasonId: string; occurredAt: string; type: string; detail: string; recorder: string; source: string }
