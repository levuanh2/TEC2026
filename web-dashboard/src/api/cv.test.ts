import { describe, expect, it } from 'vitest'
import { mapCvInference } from './cv'

describe('mapCvInference', () => {
  it('maps the exact runtime field names from backend/schemas.py::CvInferenceResponse', () => {
    const raw = {
      id: 'inf-1', crop_season_id: 'season-1', image_id: 'img-1',
      label: 'brown_spot', label_vi: 'Đốm nâu', confidence: 0.964, uncertain: false,
      threshold_used: 0.939849, model_version: 'mobilenetv2-baseline-20260909-222933',
      created_at: '2026-09-11T00:00:00Z',
    }
    expect(mapCvInference(raw)).toEqual({
      id: 'inf-1', cropSeasonId: 'season-1', imageId: 'img-1',
      label: 'brown_spot', labelVi: 'Đốm nâu', confidence: 0.964, uncertain: false,
      thresholdUsed: 0.939849, modelVersion: 'mobilenetv2-baseline-20260909-222933',
      createdAt: '2026-09-11T00:00:00Z',
    })
  })

  it('keeps label/label_vi null for an uncertain result — never a guessed label', () => {
    const raw = {
      id: 'inf-2', crop_season_id: 'season-1', image_id: 'img-2',
      label: null, label_vi: null, confidence: 0.71, uncertain: true,
      threshold_used: 0.939849, model_version: 'mobilenetv2-baseline-20260909-222933',
      created_at: '2026-09-11T00:00:00Z',
    }
    const result = mapCvInference(raw)
    expect(result.label).toBeNull()
    expect(result.labelVi).toBeNull()
    expect(result.uncertain).toBe(true)
  })
})
