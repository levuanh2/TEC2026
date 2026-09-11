// M03 CV Farmer integration: upload a leaf photo, get the existing draft
// baseline model's result back. Never fabricates a result client-side —
// every field here is exactly what the backend returned.
import { ApiError, apiRequest } from './client'
import { usingMockData } from './farms'

export type DiseaseLabel = 'rice_blast' | 'bacterial_leaf_blight' | 'brown_spot' | 'healthy'

export interface CvInference {
  id: string
  cropSeasonId: string
  imageId: string
  // null exactly when `uncertain` is true — the backend never forces one of
  // the four labels below the confidence threshold.
  label: DiseaseLabel | null
  labelVi: string | null
  confidence: number
  uncertain: boolean
  thresholdUsed: number
  modelVersion: string
  createdAt: string
}

export const mapCvInference = (x: any): CvInference => ({
  id: x.id,
  cropSeasonId: x.crop_season_id,
  imageId: x.image_id,
  label: x.label ?? null,
  labelVi: x.label_vi ?? null,
  confidence: x.confidence,
  uncertain: x.uncertain,
  thresholdUsed: x.threshold_used,
  modelVersion: x.model_version,
  createdAt: x.created_at,
})

export async function uploadAndInferLeaf(cropSeasonId: string, file: File): Promise<CvInference> {
  if (usingMockData) throw new ApiError(0, 'mock_disabled', 'Không khả dụng ở chế độ dữ liệu mẫu.')
  const form = new FormData()
  form.append('file', file)
  return mapCvInference(await apiRequest<any>(`/v1/crop-seasons/${cropSeasonId}/cv/infer`, { method: 'POST', body: form }))
}

export async function getCvInferences(cropSeasonId: string): Promise<CvInference[]> {
  if (usingMockData) return []
  return (await apiRequest<{ items: any[] }>(`/v1/crop-seasons/${cropSeasonId}/cv/inferences`)).items.map(mapCvInference)
}
