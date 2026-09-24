import { useEffect, useState, type ReactNode } from 'react'
import type { Activity } from '../types'
import { activityFields, hasDemoData } from '../utils/activityPresentation'
import { ACTIVITY_TITLE, dayLabel, groupByDay, longDay, viewActivity } from './activityView'
import type { QueryState } from './data'
import { Ico } from './icons'
import { ACTIVITY_ICON, ActivityTile, Chip, Empty, ErrorPanel, FarmerDrawer, Sk, SkBlock } from './kit'

/* Farmer farming log: day-grouped vertical timeline. Management keeps its own
 * type-grouped ActivityTimeline. Only a date is recorded, so no clock time
 * is ever shown. */

export function Timeline({ activities, renderCardActions, renderDetailActions, resetSignal }: {
  activities: Activity[]
  renderCardActions?: (activity: Activity) => ReactNode
  renderDetailActions?: (activity: Activity) => ReactNode
  resetSignal?: number
}) {
  /* The open row is tracked by id and re-resolved from `activities` on every
   * render, never kept as a snapshot: an edit invalidates this season's read,
   * and the refreshed values have to reach a drawer that is already open (a
   * snapshot showed the pre-edit amount indefinitely). Resolving by id also
   * closes the drawer by itself if the row is gone. */
  const [openId, setOpenId] = useState<string | null>(null)
  useEffect(() => setOpenId(null), [resetSignal])
  const open = openId ? activities.find((a) => a.id === openId) ?? null : null
  const setOpen = (activity: Activity | null) => setOpenId(activity?.id ?? null)
  const detail = open ? viewActivity(open) : null

  return (
    <>
      {/* The seed marks every demo row; the ledger says it once. */}
      {hasDemoData(activities) && (
        <p className="fw-demo-banner" data-testid="demo-banner">
          <Ico name="info" />Dữ liệu minh họa<span> — không phải số liệu đo ngoài ruộng, không dùng làm hồ sơ MRV chính thức.</span>
        </p>
      )}
      <ol className="fw-tl" aria-label="Nhật ký theo ngày">
        {groupByDay(activities).map((group) => (
          <li key={group.day} className="fw-tl__day">
            <div className="fw-tl__daylabel">
              <b>{dayLabel(group.day)}</b>
              <small>{group.items.length} hoạt động</small>
            </div>
            <ul className="fw-tl__items">
              {group.items.map((a) => {
                const v = viewActivity(a)
                return (
                  <li key={a.id} className={`fw-tl__item tone-${ACTIVITY_ICON[a.type]?.tone ?? 'sage'}`}>
                    <div className="fw-entry">
                      <button type="button" className="fw-entry__open" onClick={() => setOpen(a)}>
                        <ActivityTile type={a.type} />
                        <span className="fw-entry__text">
                          <span className="fw-entry__head">
                            <b>{v.title}</b>
                            <span className={`fw-entry__value${v.value ? '' : ' is-empty'}`}>{v.value ?? 'Chưa ghi lượng'}</span>
                          </span>
                          {v.meta.length > 0 && <span className="fw-entry__meta">{v.meta.join(' · ')}</span>}
                          {v.note && <span className="fw-entry__note">“{v.note}”</span>}
                        </span>
                      </button>
                      {renderCardActions && <div className="fw-entry__actions">{renderCardActions(a)}</div>}
                    </div>
                  </li>
                )
              })}
            </ul>
          </li>
        ))}
      </ol>
      {open && detail && (
        <FarmerDrawer title={detail.title} subtitle={longDay(open.occurredAt.slice(0, 10))} icon={<ActivityTile type={open.type} />} onClose={() => setOpen(null)}>
          <div className="fw-drawer__hero">
            <span className={`fw-drawer__value${detail.value ? '' : ' is-empty'}`}>{detail.value ?? 'Chưa ghi lượng'}</span>
            {detail.meta.length > 0 && <div className="fw-drawer__chips">{detail.meta.map((m) => <Chip key={m}>{m}</Chip>)}</div>}
          </div>
          <dl className="fw-detail">
            {activityFields(open.detail, open.type).map((f, i) => <div key={i}><dt>{f.label}</dt><dd>{f.value}</dd></div>)}
            <div><dt>Người ghi</dt><dd>{open.recorder}</dd></div>
          </dl>
          {renderDetailActions && <div className="fw-detail__actions">{renderDetailActions(open)}</div>}
        </FarmerDrawer>
      )}
    </>
  )
}

export function TimelineSkeleton() {
  return (
    <SkBlock label="Đang tải nhật ký" className="fw-tl">
      {[0, 1].map((d) => (
        <div key={d} className="fw-tl__day">
          <div className="fw-tl__daylabel"><Sk w={96} h={14} /><Sk w={64} h={11} /></div>
          <div className="fw-tl__items">
            {[0, 1].map((r) => (
              <div key={r} className="fw-entry fw-entry--sk"><Sk w={44} h={44} r={13} /><span className="fw-sk-lines"><Sk w="38%" h={14} /><Sk w="62%" h={12} /></span></div>
            ))}
          </div>
        </div>
      ))}
    </SkBlock>
  )
}

/** Filters + summary + timeline for one season's activities. */
export function JournalView({ state, renderCardActions, renderDetailActions, resetSignal, emptyAction, initialType }: {
  state: QueryState<Activity[]>
  /** Opens pre-filtered — "Xem hoạt động tưới" from Performance lands on the
   *  records its figure was computed from. Unknown types fall back to all. */
  initialType?: string | null
  renderCardActions?: (activity: Activity) => ReactNode
  renderDetailActions?: (activity: Activity) => ReactNode
  resetSignal?: number
  emptyAction?: ReactNode
}) {
  const [type, setType] = useState(initialType ?? 'all')
  if (state.loading) return <TimelineSkeleton />
  if (state.error) return <ErrorPanel error={state.error} onRetry={state.reload} />
  const items = state.data ?? []
  if (!items.length) return <Empty icon="journal" tone="leaf" title="Chưa có hoạt động nào trong vụ này." body="Ghi hoạt động đầu tiên để bắt đầu nhật ký canh tác." action={emptyAction} />
  const types = [...new Set(items.map((a) => a.type))]
  const current = types.includes(type) ? type : 'all'
  const shown = current === 'all' ? items : items.filter((a) => a.type === current)
  const latest = items.reduce((max, a) => (a.occurredAt > max ? a.occurredAt : max), items[0].occurredAt)
  return (
    <div className="fw-journal">
      <div className="fw-toolbar">
        <div className="fw-pills" role="group" aria-label="Lọc theo loại hoạt động">
          <button type="button" className="fw-pill" aria-pressed={current === 'all'} onClick={() => setType('all')}>Tất cả <small>{items.length}</small></button>
          {types.map((t) => (
            <button key={t} type="button" className="fw-pill" aria-pressed={current === t} onClick={() => setType(t)}>
              <Ico name={ACTIVITY_ICON[t]?.icon ?? 'journal'} />{ACTIVITY_TITLE[t] ?? t} <small>{items.filter((a) => a.type === t).length}</small>
            </button>
          ))}
        </div>
        <p className="fw-note">Lần ghi gần nhất: <b>{dayLabel(latest.slice(0, 10))}</b></p>
      </div>
      <Timeline activities={shown} renderCardActions={renderCardActions} renderDetailActions={renderDetailActions} resetSignal={resetSignal} />
    </div>
  )
}

/** Compact recent-activity list (Home, season overview). */
export function MiniTimeline({ state, limit = 4 }: { state: QueryState<Activity[]>; limit?: number }) {
  if (state.loading) {
    return (
      <SkBlock label="Đang tải hoạt động" className="fw-mini">
        {Array.from({ length: limit }).map((_, i) => <div key={i} className="fw-mini__row"><Sk w={34} h={34} r={10} /><span className="fw-sk-lines"><Sk w="40%" h={13} /><Sk w="60%" h={11} /></span><Sk w={60} h={11} /></div>)}
      </SkBlock>
    )
  }
  if (state.error) return <ErrorPanel error={state.error} onRetry={state.reload} />
  const rows = [...(state.data ?? [])].sort((a, b) => b.occurredAt.localeCompare(a.occurredAt)).slice(0, limit)
  if (!rows.length) return <Empty icon="journal" tone="leaf" title="Chưa có hoạt động nào được ghi nhận cho vụ này." body="Dùng nút Ghi hoạt động để thêm hoạt động đầu tiên." />
  return (
    <ul className="fw-mini">
      {rows.map((a) => {
        const v = viewActivity(a)
        return (
          <li key={a.id} className="fw-mini__row">
            <ActivityTile type={a.type} size="sm" />
            <div>
              <b>{v.title}</b>
              <span>{v.value && <span className="fw-mini__value">{v.value}</span>}{v.value && v.meta[0] ? ' · ' : ''}{v.meta[0] ?? (v.value ? '' : 'Chưa ghi lượng')}</span>
            </div>
            <time dateTime={a.occurredAt.slice(0, 10)}>{dayLabel(a.occurredAt.slice(0, 10))}</time>
          </li>
        )
      })}
    </ul>
  )
}
