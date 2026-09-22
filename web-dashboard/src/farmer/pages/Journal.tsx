import { useState } from 'react'
import { Link } from '../../ui'
import { ActivityCardActions, ActivityDetailActions, AddActivityCta, useActivityMutations } from '../ActivityForms'
import { Ico } from '../icons'
import { JournalView } from '../journal'
import { Empty, ErrorPanel, Flash, PageHeader } from '../kit'
import { isActiveStatus, primarySeason, seasonsOf, useActivities, useScope } from '../scope'
import { useWritableSeason } from '../writeAccess'

export function FarmerJournalPage() {
  const scope = useScope()
  const all = seasonsOf(scope.data)
  const [picked, setPicked] = useState<string | null>(null)
  const current = all.find((c) => c.season.id === picked) ?? primarySeason(scope.data) ?? all[0] ?? null
  const sid = current?.season.id ?? null
  const activities = useActivities(sid)
  const mutations = useActivityMutations()
  // Write target only when the farm role allows journal writes (not `viewer`).
  const seasonCtx = useWritableSeason(current)
  const state = scope.loading ? { ...activities, loading: true } : activities

  return (
    <>
      <PageHeader
        eyebrow="Nhật ký"
        icon="journal"
        title="Nhật ký canh tác"
        subtitle={current
          ? <>Vụ <b>{current.season.name}</b>{current.plot ? ` · ${current.plot.name}` : ''} — nhóm theo ngày, nhấn một hoạt động để xem chi tiết.</>
          : 'Mọi hoạt động đã ghi nhận của vụ, nhóm theo ngày.'}
        actions={seasonCtx ? <AddActivityCta season={seasonCtx} mutations={mutations} /> : undefined}
      />
      {all.length > 1 && (
        <div className="fw-pills" role="group" aria-label="Chọn vụ canh tác">
          {all.map((c) => (
            <button key={c.season.id} type="button" className="fw-pill" aria-pressed={c.season.id === sid} onClick={() => setPicked(c.season.id)}>
              <Ico name={isActiveStatus(c.season.status) ? 'seeding' : 'history'} />{c.season.name}{c.plot && <small>{c.plot.name}</small>}
            </button>
          ))}
        </div>
      )}
      <Flash message={mutations.flash} />
      {scope.error && !scope.data ? (
        <ErrorPanel error={scope.error} onRetry={scope.reload} />
      ) : !scope.loading && !all.length ? (
        <Empty icon="journal" title="Chưa có vụ canh tác để xem nhật ký." body="Khi ruộng của bạn có vụ canh tác, nhật ký sẽ xuất hiện ở đây." action={<Link to="/farmer/farms" className="fw-btn fw-btn--soft">Xem ruộng của tôi</Link>} />
      ) : (
        <JournalView
          state={state}
          resetSignal={mutations.version}
          renderCardActions={seasonCtx ? (a) => <ActivityCardActions activity={a} season={seasonCtx} mutations={mutations} /> : undefined}
          renderDetailActions={seasonCtx ? (a) => <ActivityDetailActions activity={a} season={seasonCtx} mutations={mutations} /> : undefined}
        />
      )}
      {mutations.node}
    </>
  )
}
