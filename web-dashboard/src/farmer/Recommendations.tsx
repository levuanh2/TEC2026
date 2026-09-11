import { useState } from 'react'
import { generateRecommendations, setRecommendationStatus, type Recommendation } from '../api/recommendations'
import { num } from '../format'
import { Async, EmptyState, Section, useAsync } from '../ui'

/**
 * M05 recommendations (brief §B23-§B26): rule-generated cards with a
 * quantified impact when one is available, honestly "Chưa thể ước tính"
 * when it isn't. Generation is idempotent (backend upserts by rule), so a
 * plain page-load reload is enough to keep the list current — no separate
 * "Generate" button.
 */
export function RecommendationsSection({ seasonId }: { seasonId: string }) {
  const state = useAsync(() => generateRecommendations(seasonId), [seasonId])
  const [busyId, setBusyId] = useState<string | null>(null)

  async function act(id: string, status: 'accepted' | 'dismissed') {
    setBusyId(id)
    try {
      await setRecommendationStatus(id, status)
    } finally {
      setBusyId(null)
      state.reload()
    }
  }

  return (
    <Section title="Khuyến nghị" description="Chỉ hiển thị khi có đủ dữ liệu để ước tính tác động; không đoán.">
      <Async
        state={state}
        skeleton="table"
        isEmpty={(items) => items.filter((item) => item.status === 'generated').length === 0}
        empty={<EmptyState icon="◌" title="Chưa có khuyến nghị định lượng" body="Hệ thống sẽ hiển thị khuyến nghị khi có đủ dữ liệu vụ này và có thể ước tính tác động." />}
      >
        {(items) => (
          <div className="farmer-recommendations">
            {items
              .filter((item) => item.status === 'generated')
              .map((item) => (
                <RecommendationCard
                  key={item.id}
                  item={item}
                  busy={busyId === item.id}
                  onAccept={() => act(item.id, 'accepted')}
                  onDismiss={() => act(item.id, 'dismissed')}
                />
              ))}
          </div>
        )}
      </Async>
    </Section>
  )
}

function RecommendationCard({ item, busy, onAccept, onDismiss }: { item: Recommendation; busy: boolean; onAccept: () => void; onDismiss: () => void }) {
  return (
    <article className="recommendation-card">
      <h3>{item.title}</h3>
      <p>{item.reason}</p>
      {item.type === 'optimization' && (
        <div className="recommendation-card__impact">
          <span>Tác động ước tính</span>
          {item.impactStatus === 'available' ? (
            <b>
              {num(item.co2eTotalKgDelta, { suffix: ' kg CO₂e', max: 1 })}
              {item.co2ePercentDelta != null && ` (giảm ${num(item.co2ePercentDelta * 100, { suffix: '%', max: 0 })})`}
            </b>
          ) : (
            <b className="is-empty">Chưa thể ước tính</b>
          )}
        </div>
      )}
      {item.comparedTo && <small className="recommendation-card__source">{item.comparedTo}</small>}
      <div className="recommendation-card__actions">
        <button type="button" className="btn btn--ghost" onClick={onDismiss} disabled={busy}>Bỏ qua</button>
        <button type="button" className="btn" onClick={onAccept} disabled={busy}>Đã hiểu</button>
      </div>
    </article>
  )
}
