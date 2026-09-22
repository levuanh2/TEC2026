import { Ico } from '../icons'
import { useEffect, useState, type ReactNode } from 'react'
import type { Activity } from '../types'
import { presentActivity, groupActivities, activityFields, ACTIVITY_GROUPS } from '../utils/activityPresentation'
import { dateTime } from '../format'
import { Drawer, EmptyState } from '../ui'

/**
 * Human-readable activity log (brief §10): grouped by kind, each row is an
 * icon + name + date + key facts — never raw JSON. Click opens a detail drawer.
 *
 * `renderActions` and `resetSignal` are optional so Management (pages/season.tsx)
 * keeps its read-only rendering unchanged; Farmer Web (FW-2 §19/§22) supplies
 * both to add edit/delete for supported activity types and to close the
 * drawer once a mutation lands.
 */
export function ActivityTimeline({ activities, renderActions, resetSignal }: { activities: Activity[]; renderActions?: (activity: Activity) => ReactNode; resetSignal?: number }) {
  const [open, setOpen] = useState<Activity | null>(null)
  useEffect(() => { setOpen(null) }, [resetSignal])
  const groups = groupActivities(activities)

  if (activities.length === 0) {
    return <EmptyState icon="straw" title="Chưa ghi nhận hoạt động nào" body="Hoạt động canh tác được nhập từ ứng dụng offline của nông hộ sẽ hiện ở đây theo nhóm." />
  }

  return (
    <>
      <div className="timeline">
        {groups.map((g) => (
          <div key={g.type} className="timeline__group">
            <div className="timeline__label">
              <Ico name={g.icon} size={15} />
              {g.label}
              <span className="count">{g.items.length}</span>
            </div>
            {g.items.map((a) => {
              const p = presentActivity(a.type, a.detail)
              return (
                <button key={a.id} className="act" onClick={() => setOpen(a)}>
                  <span className="act__icon" aria-hidden="true">
                    <Ico name={g.icon} size={15} />
                  </span>
                  <span className="act__main">
                    <span className="act__name">{p.label}</span>
                    <span className="act__sum">{p.summary}</span>
                    {p.detail && <span className="act__sub">{p.detail}</span>}
                  </span>
                  <span className="act__date">{dateTime(a.occurredAt)}</span>
                </button>
              )
            })}
          </div>
        ))}
      </div>

      {open && (
        <Drawer
          title={presentActivity(open.type, open.detail).label}
          subtitle={dateTime(open.occurredAt)}
          onClose={() => setOpen(null)}
        >
          {/* What happened in the field, in the words of the work. */}
          <dl className="dl" style={{ gridTemplateColumns: '1fr' }}>
            {activityFields(open.detail).map((f, i) => (
              <div key={i}>
                <dt>{f.label}</dt>
                <dd>{f.value}</dd>
              </div>
            ))}
            <div>
              <dt>Người ghi</dt>
              <dd>{open.recorder}</dd>
            </div>
            <div>
              <dt>Thời điểm</dt>
              <dd>{dateTime(open.occurredAt)}</dd>
            </div>
          </dl>
          {/* Record identity, the stored timestamp and the write channel are
            * what an auditor needs and what everyone else has to read past.
            * Closed by default, and present only here: the Farmer app's own
            * activity drawer has no technical section at all. */}
          <details className="tech-detail">
            <summary>Thông tin kỹ thuật</summary>
            <dl className="dl dl--tech" style={{ gridTemplateColumns: '1fr' }}>
              <div><dt>Mã bản ghi</dt><dd><code>{open.id}</code></dd></div>
              <div><dt>Thời điểm (ISO)</dt><dd><code>{open.occurredAt}</code></dd></div>
              <div><dt>Loại (giá trị lưu trữ)</dt><dd><code>{open.type}</code></dd></div>
              <div><dt>Nguồn ghi</dt><dd>{open.source}</dd></div>
            </dl>
          </details>
          {renderActions?.(open)}
        </Drawer>
      )}
    </>
  )
}

/** Compact "what's been recorded" summary for the season overview tab. */
export function ActivityCoverage({ activities }: { activities: Activity[] }) {
  return (
    <div className="grid grid-4" style={{ gap: 10 }}>
      {ACTIVITY_GROUPS.map((g) => {
        const n = activities.filter((a) => a.type === g.type).length
        return (
          <div key={g.type} className="chip" style={{ justifyContent: 'space-between' }}>
            <span>
              <Ico name={g.icon} size={14} /> {g.label}
            </span>
            <b style={{ color: n ? 'var(--brand-strong)' : 'var(--ink-faint)' }}>{n}</b>
          </div>
        )
      })}
    </div>
  )
}
