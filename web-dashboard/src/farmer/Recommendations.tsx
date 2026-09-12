import { useState } from 'react'
import { setRecommendationStatus, type Recommendation } from '../api/recommendations'
import { date, num } from '../format'
import { keys, setQueryData } from './data'
import type { IconName } from './icons'
import { Chip, Empty, ErrorPanel, IconTile, MoreLink, Refreshing, Section, Sk, SkBlock, type Tone } from './kit'
import { useRecommendations } from './scope'

/* M05 recommendations. Every number is the backend rule engine's; impact is
 * shown only when available, otherwise "Chưa thể ước tính" — never invented. */

const FAMILY: Record<string, { cls: string; icon: IconName; tone: Tone; badge: string }> = {
  optimization: { cls: 'fw-rec--action', icon: 'recommendation', tone: 'leaf', badge: 'Khuyến nghị hành động' },
  data_task: { cls: 'fw-rec--task', icon: 'task', tone: 'amber', badge: 'Cần bổ sung dữ liệu' },
}
const INFO = { cls: 'fw-rec--info', icon: 'info' as IconName, tone: 'info' as Tone, badge: 'Thông tin' }

export function RecommendationsSection({ seasonId, limit, moreTo }: { seasonId: string | null; limit?: number; moreTo?: string }) {
  const recs = useRecommendations(seasonId)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [actError, setActError] = useState<string | null>(null)

  async function act(item: Recommendation, status: 'accepted' | 'dismissed') {
    if (!seasonId) return
    setBusyId(item.id)
    setActError(null)
    try {
      const updated = await setRecommendationStatus(item.id, status)
      setQueryData(keys.recs(seasonId), (recs.data ?? []).map((r) => (r.id === updated.id ? updated : r)))
    } catch {
      setActError('Không cập nhật được khuyến nghị. Vui lòng thử lại.')
    } finally {
      setBusyId(null)
    }
  }

  const open = (recs.data ?? []).filter((r) => r.status === 'generated')
  const shown = limit ? open.slice(0, limit) : open
  return (
    <Section
      title="Khuyến nghị"
      icon="recommendation"
      tone="leaf"
      description="Chỉ hiển thị khi có đủ dữ liệu để ước tính tác động; không đoán."
      action={recs.generating && recs.data ? <Refreshing show /> : moreTo && open.length > shown.length ? <MoreLink to={moreTo}>Xem tất cả</MoreLink> : undefined}
    >
      {!seasonId ? (
        <Empty icon="recommendation" title="Chưa có vụ đang canh tác" body="Khuyến nghị gắn với một vụ canh tác cụ thể." />
      ) : recs.loading ? (
        <SkBlock label="Đang tải khuyến nghị" className="fw-recs">
          <div className="fw-rec"><Sk w={44} h={44} r={13} /><span className="fw-sk-lines"><Sk w="30%" h={12} /><Sk w="70%" h={16} /><Sk w="90%" h={12} /></span></div>
        </SkBlock>
      ) : recs.error ? (
        <ErrorPanel error={recs.error} onRetry={recs.reload} />
      ) : !shown.length ? (
        <Empty
          icon="recommendation"
          title="Chưa có khuyến nghị định lượng"
          body={recs.generating ? 'Đang kiểm tra dữ liệu mới nhất của vụ…' : 'Hệ thống sẽ hiển thị khuyến nghị khi có đủ dữ liệu vụ này và có thể ước tính tác động.'}
        />
      ) : (
        <div className="fw-recs farmer-recommendations">
          {shown.map((item) => (
            <RecommendationCard key={item.id} item={item} busy={busyId === item.id} onAccept={() => void act(item, 'accepted')} onDismiss={() => void act(item, 'dismissed')} />
          ))}
        </div>
      )}
      {actError && <p className="fw-form__error" role="alert">{actError}</p>}
      {recs.generateError && recs.data && <p className="fw-note">Chưa cập nhật được khuyến nghị mới; đang hiển thị các khuyến nghị đã lưu.</p>}
    </Section>
  )
}

function RecommendationCard({ item, busy, onAccept, onDismiss }: { item: Recommendation; busy: boolean; onAccept: () => void; onDismiss: () => void }) {
  const fam = FAMILY[item.type] ?? INFO
  return (
    <article className={`fw-rec ${fam.cls} recommendation-card`}>
      <IconTile name={fam.icon} tone={fam.tone} />
      <div className="fw-rec__body">
        <div className="fw-rec__top">
          <Chip tone={fam.tone}>{fam.badge}</Chip>
          <time dateTime={item.generatedAt}>{date(item.generatedAt)}</time>
        </div>
        <h3>{item.title}</h3>
        <p className="fw-rec__reason">{item.reason}</p>
        {item.type === 'optimization' && (
          <div className="fw-rec__impact">
            <span>Tác động ước tính</span>
            {item.impactStatus === 'available' ? (
              <b>
                {num(item.co2eTotalKgDelta, { suffix: ' kg CO₂e', max: 1 })}
                {item.co2ePercentDelta != null && ` (giảm ${num(item.co2ePercentDelta * 100, { suffix: '%', max: 0 })})`}
              </b>
            ) : (
              <b className="is-empty">Chưa thể ước tính</b>
            )}
            {item.impactStatus !== 'available' && item.impactUnavailableReason && <small>{item.impactUnavailableReason}</small>}
          </div>
        )}
        {item.comparedTo && <p className="fw-rec__source">So sánh với: {item.comparedTo}</p>}
        <div className="fw-rec__actions">
          <button type="button" className="fw-btn fw-btn--ghost fw-btn--sm" onClick={onDismiss} disabled={busy}>Bỏ qua</button>
          <button type="button" className="fw-btn fw-btn--sm" onClick={onAccept} disabled={busy}>Đã hiểu</button>
        </div>
      </div>
    </article>
  )
}
