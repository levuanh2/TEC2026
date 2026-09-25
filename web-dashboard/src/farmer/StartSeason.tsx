import { useState } from 'react'
import type { FarmerScope } from '../api/farms'
import type { StartedSeason } from '../api/crops'
import { StartSeasonForm } from '../features/startSeason'
import type { Plot } from '../types'
import { go, Link } from '../ui'
import { invalidateQueries, keys, peekQuery, setQueryData } from './data'
import { Ico } from './icons'
import { Empty, FarmerSheet } from './kit'
import { isActiveStatus, useScope } from './scope'
import { useCanWriteFarm } from './writeAccess'

/** Plots the viewer may start a season on right now: their farm role allows
 * writing and nothing is under cultivation there (the server refuses a second
 * active season on one plot). */
export function useStartablePlots(scope: FarmerScope | undefined): Plot[] {
  const canWrite = useCanWriteFarm()
  if (!scope) return []
  return scope.plots.filter((p) => canWrite(p.farmId) && !scope.seasons.some((s) => s.plotId === p.id && isActiveStatus(s.status)))
}

/** The query string a freshly started season is opened with, so its page can
 * offer the next step ("Ghi hoạt động đầu tiên") once. */
export const NEW_SEASON_PARAM = 'vu-moi'

/** Put the new season into the cached scope at once, then refetch it: the
 * season page it navigates to must find the season without waiting. */
function remember(started: StartedSeason): void {
  const current = peekQuery<FarmerScope>(keys.scope)
  if (current) setQueryData<FarmerScope>(keys.scope, { ...current, seasons: [...current.seasons.filter((s) => s.id !== started.season.id), started.season] })
  invalidateQueries(keys.scope)
}

/** "Bắt đầu vụ mới" for the Farmer experience: `open(plots)` shows the sheet;
 * on success the viewer lands on the new season. */
export function useStartSeason() {
  const [target, setTarget] = useState<{ plots: Plot[]; plotId?: string } | null>(null)
  const close = () => setTarget(null)
  const node = target ? (
    <FarmerSheet title="Bắt đầu vụ mới" subtitle="Vụ mới sẽ dùng để ghi nhật ký, theo dõi hiệu suất và tính Carbon." icon="seeding" tone="leaf" onClose={close}>
      <StartSeasonForm
        variant="farmer"
        plots={target.plots}
        initialPlotId={target.plotId}
        onCancel={close}
        onStarted={(started) => {
          remember(started)
          setTarget(null)
          go(`/farmer/crop-seasons/${started.season.id}?${NEW_SEASON_PARAM}=1`)
        }}
      />
    </FarmerSheet>
  ) : null
  return { open: (plots: Plot[], plotId?: string) => setTarget({ plots, plotId }), node }
}

const PURPOSE_BODY: Record<'journal' | 'home' | 'performance' | 'carbon', string> = {
  journal: 'Bạn cần bắt đầu một vụ trên thửa ruộng trước khi ghi nhật ký hoạt động.',
  home: 'Bạn cần bắt đầu một vụ trên thửa ruộng trước khi ghi nhật ký hoạt động.',
  performance: 'Hiệu suất được tính cho một vụ. Bạn cần bắt đầu một vụ trên thửa ruộng và ghi nhật ký trước.',
  carbon: 'Carbon được tính cho một vụ. Bạn cần bắt đầu một vụ trên thửa ruộng và ghi nhật ký trước.',
}

/** Nothing under cultivation. Names the lifecycle step the account is at --
 * no plot assigned yet, or a plot without a running season -- and offers the
 * one step that moves it on, instead of an empty page that looks broken or an
 * empty journal that looks ready to write in. */
export function NoActiveSeason({ purpose }: { purpose: keyof typeof PURPOSE_BODY }) {
  const scope = useScope()
  const startable = useStartablePlots(scope.data)
  const start = useStartSeason()
  if (!scope.data?.plots.length) {
    return (
      <Empty icon="plot" title="HTX chưa gán thửa ruộng cho tài khoản của bạn."
        body="Mỗi vụ canh tác thuộc một thửa ruộng. Liên hệ cán bộ hợp tác xã để được gán thửa; sau đó bạn có thể bắt đầu vụ và ghi nhật ký." />
    )
  }
  const hadSeasons = scope.data.seasons.length > 0
  return (
    <>
      <Empty
        icon="seeding"
        tone="leaf"
        title="Bạn chưa có vụ đang canh tác"
        body={<>
          {PURPOSE_BODY[purpose]}
          {!startable.length && ' Bạn chưa có quyền tạo vụ canh tác — hãy liên hệ chủ hộ hoặc cán bộ hợp tác xã.'}
          {hadSeasons && purpose !== 'journal' && ' Các vụ đã kết thúc vẫn xem được trong Ruộng / Vụ mùa.'}
        </>}
        action={startable.length
          ? <button type="button" className="fw-btn" onClick={() => start.open(startable)}><Ico name="plus" />Bắt đầu vụ mới</button>
          : <Link to="/farmer/farms" className="fw-btn fw-btn--soft">Xem ruộng của tôi</Link>}
      />
      {start.node}
    </>
  )
}
