import { useEffect, useState, type ReactNode } from 'react'
import type { Activity } from '../types'
import { activityFields, activityIcon, presentActivity } from '../utils/activityPresentation'
import { date } from '../format'
import { Drawer, EmptyState } from '../ui'

/**
 * Farmer-facing activity timeline, grouped by DATE (not by activity type
 * like the Management read-only ActivityTimeline in features/activities.tsx)
 * — a farmer thinks "what did I do on the 11th", not "show me every
 * fertilizer application ever". Kept as its own component rather than
 * reworking the shared one so Management's already-reviewed presentation
 * is untouched.
 *
 * `renderActions`/`resetSignal` mirror ActivityTimeline's API so the two
 * are drop-in compatible for callers that already wire edit/delete.
 */
export function FarmerJournalTimeline({
  activities,
  renderActions,
  resetSignal,
}: {
  activities: Activity[]
  renderActions?: (activity: Activity) => ReactNode
  resetSignal?: number
}) {
  const [open, setOpen] = useState<Activity | null>(null)
  useEffect(() => setOpen(null), [resetSignal])

  if (activities.length === 0) {
    return <EmptyState icon="🌾" title="Chưa có hoạt động nào trong vụ này." body="Ghi nhanh một hoạt động để bắt đầu nhật ký." />
  }

  const byDate = new Map<string, Activity[]>()
  for (const a of [...activities].sort((x, y) => y.occurredAt.localeCompare(x.occurredAt))) {
    const key = a.occurredAt.slice(0, 10)
    if (!byDate.has(key)) byDate.set(key, [])
    byDate.get(key)!.push(a)
  }

  return (
    <>
      <div className="f-journal">
        {[...byDate.entries()].map(([day, items]) => (
          <div key={day} className="f-journal__day">
            <div className="f-journal__date">{date(day)}</div>
            <div className="f-journal__rows">
              {items.map((a) => {
                const p = presentActivity(a.type, a.detail)
                return (
                  <button key={a.id} type="button" className="f-journal__row" onClick={() => setOpen(a)}>
                    <span className="f-journal__icon" aria-hidden="true">{activityIcon(a.type)}</span>
                    <span className="f-journal__body">
                      <span className="f-journal__title">{p.label}</span>
                      <span className="f-journal__value">{p.summary}</span>
                      {p.detail && <span className="f-journal__meta">{p.detail}</span>}
                    </span>
                    <span className="f-journal__chev" aria-hidden="true">›</span>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      {open && (
        <Drawer title={presentActivity(open.type, open.detail).label} subtitle={date(open.occurredAt)} onClose={() => setOpen(null)}>
          <dl className="dl" style={{ gridTemplateColumns: '1fr' }}>
            {activityFields(open.detail).map((f, i) => (
              <div key={i}><dt>{f.label}</dt><dd>{f.value}</dd></div>
            ))}
            <div><dt>Người ghi</dt><dd>{open.recorder}</dd></div>
          </dl>
          {renderActions?.(open)}
        </Drawer>
      )}
    </>
  )
}
