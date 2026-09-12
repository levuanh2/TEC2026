import type { SeasonMetrics } from '../api/metrics'
import { perKg } from '../format'
import { fmtNumber, type QuickType } from './activityView'
import type { IconName } from './icons'
import type { Tone } from './kit'

/* View model for the four resource metrics. Values come straight from the
 * backend MetricResponse; nothing is estimated, graded or benchmarked here. */

export interface MetricView {
  key: 'water' | 'fertilizer' | 'cost' | 'carbon'
  label: string
  icon: IconName
  tone: Tone
  unit: string
  value: string | null
  explain: string
  basis: string | null
  emptyHint: string
  shortHint: string
  cta?: QuickType
}

const money = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 })

export function metricViews(m: SeasonMetrics): MetricView[] {
  const needYield = m.yieldKg == null
  const yieldText = m.yieldKg == null ? null : `${fmtNumber(m.yieldKg)} kg thóc`
  const ratio = (v: number | null) => (v == null ? null : perKg(v, ''))
  const missing = (own: string, short: string, cta?: QuickType) => needYield
    ? { emptyHint: 'Cần ghi nhận sản lượng thu hoạch để tính chỉ số trên mỗi kg lúa.', shortHint: 'Cần sản lượng thu hoạch', cta: 'harvest' as QuickType }
    : { emptyHint: own, shortHint: short, cta }
  return [
    {
      key: 'water', label: 'Nước tưới', icon: 'irrigation', tone: 'water', unit: 'm³ / kg lúa', value: ratio(m.waterPerKg),
      explain: 'Tổng lượng nước tưới đã ghi nhận chia cho sản lượng thóc.',
      basis: m.waterM3 != null && yieldText ? `Dựa trên ${fmtNumber(m.waterM3)} m³ nước và ${yieldText} đã ghi nhận` : null,
      ...missing('Hãy ghi nhận hoạt động tưới (có lượng nước) để xem chỉ số này.', 'Cần ghi lượng nước tưới', 'irrigation'),
    },
    {
      key: 'fertilizer', label: 'Phân bón', icon: 'fertilizer', tone: 'earth', unit: 'kg / kg lúa', value: ratio(m.fertilizerPerKg),
      explain: 'Khối lượng phân bón vật lý đã ghi nhận chia cho sản lượng thóc.',
      basis: m.fertilizerKg != null && yieldText ? `Dựa trên ${fmtNumber(m.fertilizerKg)} kg phân và ${yieldText} đã ghi nhận` : null,
      ...missing('Hãy ghi nhận các lần bón phân để xem chỉ số này.', 'Cần ghi lần bón phân', 'fertilizer'),
    },
    {
      key: 'cost', label: 'Chi phí vật tư', icon: 'money', tone: 'straw', unit: '₫ / kg lúa', value: m.costPerKg == null ? null : money.format(m.costPerKg),
      explain: 'Chi phí vật tư đã nhập trong các hoạt động chia cho sản lượng — không phải tổng chi phí sản xuất.',
      basis: m.costPerKg != null && yieldText ? `Dựa trên ${yieldText} đã ghi nhận` : null,
      ...missing('Nhập chi phí vật tư khi ghi hoạt động để xem chỉ số này.', 'Cần nhập chi phí vật tư'),
    },
    {
      key: 'carbon', label: 'Carbon', icon: 'carbon', tone: 'carbon', unit: 'kg CO₂e / kg lúa', value: ratio(m.co2ePerKg),
      explain: 'Phát thải ước tính từ kết quả tính Carbon hợp lệ của vụ.',
      basis: m.totalCo2eKg != null ? `Tổng ${fmtNumber(m.totalCo2eKg)} kg CO₂e của vụ` : null,
      ...(m.completeness.carbon
        ? missing('Chỉ hiển thị khi vụ có kết quả tính phát thải hợp lệ.', 'Chưa có kết quả hợp lệ')
        : { emptyHint: 'Chỉ hiển thị khi vụ có kết quả tính phát thải hợp lệ.', shortHint: 'Chưa có kết quả hợp lệ' }),
    },
  ]
}
