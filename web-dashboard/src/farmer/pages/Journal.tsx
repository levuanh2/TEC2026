import { useState } from 'react'
import { ActivityCardActions, ActivityDetailActions, AddActivityCta, useActivityMutations } from '../ActivityForms'
import { Ico } from '../icons'
import { JournalView } from '../journal'
import { Empty, ErrorPanel, Flash, PageHeader, Section } from '../kit'
import { activeSeasonsOf, isActiveStatus, primarySeason, seasonsOf, useActivities, useScope, type SeasonCtx } from '../scope'
import { NoActiveSeason } from '../StartSeason'
import { useWritableSeason } from '../writeAccess'

export function FarmerJournalPage() {
  const scope = useScope()
  const all = seasonsOf(scope.data)
  const hasActive = activeSeasonsOf(scope.data).length > 0
  const [picked, setPicked] = useState<string | null>(null)
  // With no active season, the fallback is a past season to READ: whatever is
  // selected, `useWritableSeason` only offers writes for an open season.
  const current = all.find((c) => c.season.id === picked) ?? primarySeason(scope.data) ?? all[0] ?? null
  const sid = current?.season.id ?? null
  const activities = useActivities(sid)
  const mutations = useActivityMutations()
  // Write target only for an open season on a farm the role may write to.
  const seasonCtx = useWritableSeason(current)
  const state = scope.loading ? { ...activities, loading: true } : activities
  const loaded = !scope.loading && Boolean(scope.data)

  return (
    <>
      <PageHeader
        eyebrow="Nhật ký"
        icon="journal"
        title="Nhật ký canh tác"
        subtitle={current && (hasActive || !loaded)
          ? <>Vụ <b>{current.season.name}</b>{current.plot ? ` · ${current.plot.name}` : ''} — nhóm theo ngày, nhấn một hoạt động để xem chi tiết.</>
          : 'Nhật ký được ghi theo từng vụ canh tác trên thửa ruộng.'}
        actions={seasonCtx ? <AddActivityCta season={seasonCtx} mutations={mutations} /> : undefined}
      />
      <Flash message={mutations.flash} />
      {scope.error && !scope.data ? (
        <ErrorPanel error={scope.error} onRetry={scope.reload} />
      ) : loaded && !hasActive ? (
        <>
          <NoActiveSeason purpose="journal" />
          {all.length > 0 && (
            <Section title="Nhật ký các vụ trước" icon="history" tone="sage" description="Chỉ để xem — vụ đã kết thúc không nhận thêm hoạt động.">
              <SeasonPills all={all} sid={sid} onPick={setPicked} />
              <JournalView state={state} initialType={new URLSearchParams(location.search).get('loai')} resetSignal={mutations.version} />
            </Section>
          )}
        </>
      ) : (
        <>
          <SeasonPills all={all} sid={sid} onPick={setPicked} />
          <JournalView
            state={state}
            initialType={new URLSearchParams(location.search).get('loai')}
            resetSignal={mutations.version}
            renderCardActions={seasonCtx ? (a) => <ActivityCardActions activity={a} season={seasonCtx} mutations={mutations} /> : undefined}
            renderDetailActions={seasonCtx ? (a) => <ActivityDetailActions activity={a} season={seasonCtx} mutations={mutations} /> : undefined}
          />
        </>
      )}
      {mutations.node}
    </>
  )
}

function SeasonPills({ all, sid, onPick }: { all: SeasonCtx[]; sid: string | null; onPick: (id: string) => void }) {
  if (all.length < 2) return null
  return (
    <div className="fw-pills" role="group" aria-label="Chọn vụ canh tác">
      {all.map((c) => (
        <button key={c.season.id} type="button" className="fw-pill" aria-pressed={c.season.id === sid} onClick={() => onPick(c.season.id)}>
          <Ico name={isActiveStatus(c.season.status) ? 'seeding' : 'history'} />{c.season.name}{c.plot && <small>{c.plot.name}</small>}
        </button>
      ))}
    </div>
  )
}
