// M05 recommendations: read-only display + accept/dismiss. Every number here
// comes straight from the backend rule engine (which itself only ever calls
// back into the real Carbon Engine for carbon-impact evidence) — this file
// does no math of its own, ever (brief M05 §B3/§B7/§B25).
import { apiRequest } from './client'
import { usingMockData } from './farms'

export type RecommendationType = 'optimization' | 'data_task'
export type RecommendationStatus = 'generated' | 'accepted' | 'dismissed' | 'expired'
export type ImpactStatus = 'available' | 'unavailable'

export interface Recommendation {
  id: string
  cropSeasonId: string
  ruleCode: string
  ruleVersion: string
  engineVersion: string | null
  type: RecommendationType
  status: RecommendationStatus
  title: string
  reason: string
  comparedTo: string | null
  co2eTotalKgBefore: number | null
  co2eTotalKgAfter: number | null
  co2eTotalKgDelta: number | null
  co2ePercentDelta: number | null
  impactStatus: ImpactStatus
  impactUnavailableReason: string | null
  generatedAt: string
  acceptedAt: string | null
  dismissedAt: string | null
}

export const mapRecommendation = (x: any): Recommendation => ({
  id: x.id,
  cropSeasonId: x.crop_season_id,
  ruleCode: x.rule_code,
  ruleVersion: x.rule_version,
  engineVersion: x.engine_version ?? null,
  type: x.type,
  status: x.status,
  title: x.title,
  reason: x.reason,
  comparedTo: x.compared_to ?? null,
  co2eTotalKgBefore: x.co2e_total_kg_before ?? null,
  co2eTotalKgAfter: x.co2e_total_kg_after ?? null,
  co2eTotalKgDelta: x.co2e_total_kg_delta ?? null,
  co2ePercentDelta: x.co2e_percent_delta ?? null,
  impactStatus: x.impact_status,
  impactUnavailableReason: x.impact_unavailable_reason ?? null,
  generatedAt: x.generated_at,
  acceptedAt: x.accepted_at ?? null,
  dismissedAt: x.dismissed_at ?? null,
})

export async function getRecommendations(cropSeasonId: string): Promise<Recommendation[]> {
  if (usingMockData) return []
  return (await apiRequest<{ items: any[] }>(`/v1/crop-seasons/${cropSeasonId}/recommendations`)).items.map(mapRecommendation)
}

export async function generateRecommendations(cropSeasonId: string): Promise<Recommendation[]> {
  if (usingMockData) return []
  return (await apiRequest<{ items: any[] }>(`/v1/crop-seasons/${cropSeasonId}/recommendations/generate`, { method: 'POST' })).items.map(mapRecommendation)
}

export async function setRecommendationStatus(id: string, status: 'accepted' | 'dismissed'): Promise<Recommendation> {
  return mapRecommendation(await apiRequest<any>(`/v1/recommendations/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }))
}
