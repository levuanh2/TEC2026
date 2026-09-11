import { describe, expect, it } from 'vitest'
import { mapRecommendation } from './recommendations'

describe('mapRecommendation', () => {
  it('maps the exact runtime field names from backend/schemas.py::RecommendationResponse', () => {
    const raw = {
      id: 'rec-1', crop_season_id: 'season-1', rule_code: 'water.awd_from_continuous_flooding',
      rule_version: '1', engine_version: '0.2.0', type: 'optimization', status: 'generated',
      title: 'Cân nhắc tưới AWD (ướt khô xen kẽ)', reason: 'vì sao', compared_to: 'Kịch bản AWD tính bởi Carbon Engine',
      co2e_total_kg_before: 5435.4, co2e_total_kg_after: 2920.8, co2e_total_kg_delta: 2514.6,
      co2e_percent_delta: 0.4627, impact_status: 'available', impact_unavailable_reason: null,
      generated_at: '2026-09-11T00:00:00Z', accepted_at: null, dismissed_at: null,
    }
    expect(mapRecommendation(raw)).toEqual({
      id: 'rec-1', cropSeasonId: 'season-1', ruleCode: 'water.awd_from_continuous_flooding',
      ruleVersion: '1', engineVersion: '0.2.0', type: 'optimization', status: 'generated',
      title: 'Cân nhắc tưới AWD (ướt khô xen kẽ)', reason: 'vì sao', comparedTo: 'Kịch bản AWD tính bởi Carbon Engine',
      co2eTotalKgBefore: 5435.4, co2eTotalKgAfter: 2920.8, co2eTotalKgDelta: 2514.6,
      co2ePercentDelta: 0.4627, impactStatus: 'available', impactUnavailableReason: null,
      generatedAt: '2026-09-11T00:00:00Z', acceptedAt: null, dismissedAt: null,
    })
  })

  it('keeps a null (unavailable) impact null, never coerced to 0', () => {
    const raw = {
      id: 'rec-2', crop_season_id: 'season-1', rule_code: 'data.completeness.yield',
      rule_version: '1', engine_version: null, type: 'data_task', status: 'generated',
      title: 'Ghi sản lượng thu hoạch', reason: '...', compared_to: null,
      co2e_total_kg_before: null, co2e_total_kg_after: null, co2e_total_kg_delta: null,
      co2e_percent_delta: null, impact_status: 'unavailable',
      impact_unavailable_reason: 'Đây là gợi ý bổ sung dữ liệu, không phải khuyến nghị tối ưu hoá có định lượng.',
      generated_at: '2026-09-11T00:00:00Z', accepted_at: null, dismissed_at: null,
    }
    const result = mapRecommendation(raw)
    expect(result.co2eTotalKgDelta).toBeNull()
    expect(result.impactStatus).toBe('unavailable')
    expect(result.type).toBe('data_task')
  })
})
