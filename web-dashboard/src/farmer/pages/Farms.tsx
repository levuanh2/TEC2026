import type { FarmerScope } from '../../api/farms'
import type { CropSeason, Farm, Plot } from '../../types'
import { date, daysSince, ha } from '../../format'
import { Link } from '../../ui'
import { fmtNumber } from '../activityView'
import { Ico } from '../icons'
import { Crumbs, Empty, ErrorPanel, IconTile, PageHeader, Section, Sk, SkBlock, Stat } from '../kit'
import {
  isActiveStatus, placeOf, plotsOfFarm, prefetchSeason, seasonStatusLabel, seasonsOfPlot, seasonsOfPlots, sumArea, useScope,
} from '../scope'
import { useStartSeason } from '../StartSeason'
import { useCanWriteFarm } from '../writeAccess'

const NOT_FOUND = 'Không tìm thấy dữ liệu hoặc dữ liệu không thuộc phạm vi truy cập.'

/* ----------------------------------------------------------------- list */

export function FarmerFarmsPage() {
  const scope = useScope()
  return (
    <>
      <PageHeader eyebrow="Ruộng của tôi" icon="farm" title="Các ruộng trong phạm vi của bạn" subtitle="Nông hộ, thửa ruộng và vụ canh tác mà tài khoản của bạn được cấp quyền." />
      {scope.loading ? (
        <SkBlock label="Đang tải ruộng" className="fw-farms">
          {[0, 1].map((i) => (
            <div key={i} className="fw-farm">
              <div className="fw-farm__band" />
              <div className="fw-farm__body">
                <div className="fw-farm__id"><Sk w={58} h={58} r={17} /><span className="fw-sk-lines"><Sk w="60%" h={18} /><Sk w="40%" h={12} /></span></div>
                <div className="fw-stats">{[0, 1, 2].map((j) => <Sk key={j} h={54} r={12} />)}</div>
              </div>
            </div>
          ))}
        </SkBlock>
      ) : scope.error || !scope.data ? (
        <ErrorPanel error={scope.error ?? 'Không có dữ liệu.'} onRetry={scope.reload} />
      ) : !scope.data.farms.length ? (
        <Empty icon="farm" title="Chưa có ruộng nào" body="Chưa có nông hộ nào được cấp quyền cho tài khoản này. Liên hệ quản lý HTX để được gán." />
      ) : (
        <div className="fw-farms">{scope.data.farms.map((farm) => <FarmCard key={farm.id} farm={farm} scope={scope.data!} />)}</div>
      )}
    </>
  )
}

function FarmCard({ farm, scope }: { farm: Farm; scope: FarmerScope }) {
  const plots = plotsOfFarm(scope, farm.id)
  const seasons = seasonsOfPlots(scope, plots)
  const active = seasons.filter((s) => isActiveStatus(s.status))
  const area = sumArea(plots)
  const place = placeOf(farm)
  return (
    <article className="fw-farm farmer-farm-card">
      <div className="fw-farm__band" aria-hidden="true" />
      <div className="fw-farm__body">
        <div className="fw-farm__id">
          <IconTile name="farm" tone="forest" size="lg" />
          <div><h2>{farm.name}</h2><small>Mã hộ {farm.code}{place ? ` · ${place}` : ''}</small></div>
        </div>
        <div className="fw-stats">
          <Stat value={area == null ? 'Chưa có' : ha(area)} label="diện tích" empty={area == null} />
          <Stat value={plots.length} label="thửa" />
          <Stat value={active.length} label="vụ đang canh tác" />
        </div>
        {/* The card used to name one active season out of however many the
          * farm has, then stop — the reader had to open the farm to find the
          * others, and the page was a single line in a lot of white. The
          * hierarchy is on the page now: each plot, and the season on it. */}
        <ul className="fw-farm__plots">
          {plots.map((plot) => {
            const on = seasons.filter((x) => x.plotId === plot.id)
            const running = on.find((x) => isActiveStatus(x.status))
            return (
              <li key={plot.id}>
                <Link to={`/farmer/plots/${plot.id}`} className="fw-farm__plot">
                  <span className="fw-farm__plotname"><Ico name="plot" />{plot.name}</span>
                  <span className="fw-farm__plotarea">{plot.areaHa == null ? '—' : ha(plot.areaHa)}</span>
                  <span className="fw-farm__plotseason">
                    {running
                      ? <><b>{running.name}</b><span className="fw-chip tone-leaf">Đang canh tác</span></>
                      : <span className="fw-muted">Chưa có vụ đang canh tác</span>}
                  </span>
                  <Ico name="chevron" />
                </Link>
              </li>
            )
          })}
          {!plots.length && <li className="fw-note">Nông hộ này chưa có thửa ruộng nào được ghi nhận.</li>}
        </ul>
        <div className="fw-farm__foot">
          <Link to={`/farmer/farms/${farm.id}`} className="fw-btn fw-btn--soft" aria-label={`Xem hồ sơ nông hộ ${farm.name}`}>Xem hồ sơ nông hộ<Ico name="arrow" /></Link>
        </div>
      </div>
    </article>
  )
}

/* ------------------------------------------------------------ farm detail */

function DetailSkeleton() {
  return (
    <SkBlock label="Đang tải" className="fw-stack-lg">
      <Sk w={220} h={14} />
      <div className="fw-idcard">
        <div className="fw-idcard__top"><Sk w={58} h={58} r={17} /><span className="fw-sk-lines"><Sk w="40%" h={26} /><Sk w="30%" h={13} /></span></div>
        <div className="fw-stats">{[0, 1, 2].map((i) => <Sk key={i} h={54} r={12} />)}</div>
      </div>
      <div className="fw-plots">{[0, 1].map((i) => <Sk key={i} h={150} r={20} />)}</div>
    </SkBlock>
  )
}

export function FarmerFarmPage({ id }: { id: string }) {
  const scope = useScope()
  if (scope.loading) return <DetailSkeleton />
  if (scope.error || !scope.data) return <ErrorPanel error={scope.error ?? 'Không có dữ liệu.'} onRetry={scope.reload} />
  const farm = scope.data.farms.find((f) => f.id === id)
  if (!farm) return <><Crumbs items={[{ label: 'Ruộng của tôi', to: '/farmer/farms' }, { label: 'Nông hộ' }]} /><ErrorPanel error={NOT_FOUND} /></>
  const plots = plotsOfFarm(scope.data, farm.id)
  const seasons = seasonsOfPlots(scope.data, plots)
  const active = seasons.filter((s) => isActiveStatus(s.status))
  const area = sumArea(plots)
  const place = placeOf(farm)
  return (
    <>
      <Crumbs items={[{ label: 'Ruộng của tôi', to: '/farmer/farms' }, { label: farm.name }]} />
      <section className="fw-idcard">
        <div className="fw-idcard__top">
          <IconTile name="farm" tone="forest" size="lg" />
          <div>
            <p className="fw-head__eyebrow">Nông hộ</p>
            <h1>{farm.name}</h1>
            <p className="fw-idcard__meta"><span><Ico name="pin" />{place || 'Chưa có địa chỉ'}</span><span>Mã hộ {farm.code}</span></p>
          </div>
        </div>
        <div className="fw-stats">
          <Stat value={area == null ? 'Chưa có' : ha(area)} label="tổng diện tích các thửa" empty={area == null} />
          <Stat value={plots.length} label="thửa ruộng" />
          <Stat value={active.length} label="vụ đang canh tác" />
        </div>
        {/* One next action. The page used to end with a "Vụ đang canh tác"
          * section that listed the same seasons the plot cards above already
          * named, so the running season was stated twice on one screen. */}
        {active[0] && (
          <div className="fw-idcard__action">
            <Link to={`/farmer/crop-seasons/${active[0].id}/journal`} className="fw-btn" onMouseEnter={() => prefetchSeason(active[0].id)}>
              <Ico name="journal" />Ghi hoạt động cho {active[0].name}
            </Link>
          </div>
        )}
      </section>
      <Section title="Thửa ruộng" icon="plot" tone="leaf" description={`${plots.length} thửa trong nông hộ này`}>
        {plots.length
          ? <div className="fw-plots">{plots.map((plot) => <PlotCard key={plot.id} plot={plot} seasons={seasonsOfPlot(scope.data!, plot.id)} />)}</div>
          : <Empty icon="plot" tone="leaf" title="Chưa có thửa ruộng nào" body="Nông hộ này chưa có thửa ruộng được ghi nhận." />}
      </Section>

    </>
  )
}

function PlotCard({ plot, seasons }: { plot: Plot; seasons: CropSeason[] }) {
  const active = seasons.find((s) => isActiveStatus(s.status))
  return (
    <Link to={`/farmer/plots/${plot.id}`} className="fw-plot farmer-plot-card" onMouseEnter={() => active && prefetchSeason(active.id)}>
      <span className="fw-plot__top"><IconTile name="plot" tone="leaf" /><span><b>{plot.name}</b><small>Mã thửa {plot.code}</small></span></span>
      <span className="fw-plot__area">{plot.areaHa == null ? 'Chưa có diện tích' : <>{fmtNumber(plot.areaHa)} <small>ha</small></>}</span>
      <span className={`fw-plot__season${active ? '' : ' is-idle'}`}>
        {active ? <><span>Đang canh tác</span><b>{active.name}</b></> : <span>Chưa có vụ đang canh tác</span>}
      </span>
    </Link>
  )
}

function SeasonRow({ season, plot, past }: { season: CropSeason; plot?: Plot; past?: boolean }) {
  const meta = [plot?.name, season.variety && `Giống ${season.variety}`, season.plantingDate && `Gieo ${date(season.plantingDate)}`].filter(Boolean).join(' · ')
  return (
    <Link to={`/farmer/crop-seasons/${season.id}`} className={`fw-season${past ? ' fw-season--past' : ''}`} onMouseEnter={() => prefetchSeason(season.id)} onFocus={() => prefetchSeason(season.id)}>
      <IconTile name={past ? 'history' : 'seeding'} tone={past ? 'sage' : 'leaf'} />
      <span><b>{season.name}</b><small>{meta || 'Chưa có thông tin giống / ngày gieo'}</small></span>
      <span className="fw-season__go"><span className={`fw-chip tone-${past ? 'sage' : 'leaf'}`}>{seasonStatusLabel(season.status)}</span><Ico name="chevron" /></span>
    </Link>
  )
}

/* ------------------------------------------------------------ plot detail */

export function FarmerPlotPage({ id }: { id: string }) {
  const scope = useScope()
  const canWrite = useCanWriteFarm()
  const start = useStartSeason()
  if (scope.loading) return <DetailSkeleton />
  if (scope.error || !scope.data) return <ErrorPanel error={scope.error ?? 'Không có dữ liệu.'} onRetry={scope.reload} />
  const plot = scope.data.plots.find((p) => p.id === id)
  if (!plot) return <><Crumbs items={[{ label: 'Ruộng của tôi', to: '/farmer/farms' }, { label: 'Thửa ruộng' }]} /><ErrorPanel error={NOT_FOUND} /></>
  const farm = scope.data.farms.find((f) => f.id === plot.farmId)
  const seasons = seasonsOfPlot(scope.data, plot.id)
  const active = seasons.find((s) => isActiveStatus(s.status))
  const days = active && !active.harvestDate ? daysSince(active.plantingDate) : null
  const past = seasons.filter((x) => x.id !== active?.id)
  // Starting a season is offered only where the farm role allows writing and
  // nothing is under cultivation — the server refuses anything else anyway.
  const canStart = !active && canWrite(plot.farmId)
  const startButton = <button type="button" className="fw-btn" onClick={() => start.open([plot])}><Ico name="plus" />Bắt đầu vụ mới</button>
  return (
    <>
      <Crumbs items={[{ label: 'Ruộng của tôi', to: '/farmer/farms' }, ...(farm ? [{ label: farm.name, to: `/farmer/farms/${farm.id}` }] : []), { label: plot.name }]} />
      <section className="fw-idcard">
        <div className="fw-idcard__top">
          <IconTile name="plot" tone="leaf" size="lg" />
          <div>
            <p className="fw-head__eyebrow">Thửa ruộng</p>
            <h1>{plot.name}</h1>
            <p className="fw-idcard__meta"><span>Mã thửa {plot.code}</span>{farm && <span><Ico name="farm" />{farm.name}</span>}</p>
          </div>
        </div>
        <div className="fw-stats">
          <Stat value={plot.areaHa == null ? 'Chưa có' : ha(plot.areaHa)} label="diện tích" empty={plot.areaHa == null} />
          <Stat value={seasons.length} label="vụ đã ghi nhận" />
          <Stat value={active ? 1 : 0} label="vụ đang canh tác" />
        </div>
      </section>
      {/* The running season was featured here AND listed again below, so the
        * same season appeared twice on one screen. It is stated once: as the
        * highlighted head of the season list, carrying the page's one action. */}
      {active && (
        <Link to={`/farmer/crop-seasons/${active.id}`} className="fw-current" onMouseEnter={() => prefetchSeason(active.id)}>
          <span>
            <span className="fw-current__label">Vụ đang canh tác</span>
            <b>{active.name}</b>
            <small>{[active.variety && `Giống ${active.variety}`, active.plantingDate && `Gieo ${date(active.plantingDate)}`, days != null && `${days} ngày canh tác`].filter(Boolean).join(' · ')}</small>
          </span>
          <span className="fw-btn">Mở vụ<Ico name="arrow" /></span>
        </Link>
      )}
      {seasons.length > 0 && !active && (
        <div className="fw-current fw-current--idle">
          <span>
            <span className="fw-current__label">Chưa có vụ đang canh tác</span>
            <small>{canStart ? 'Bắt đầu vụ mới để ghi nhật ký, theo dõi hiệu suất và tính Carbon.' : 'Bạn chưa có quyền tạo vụ canh tác.'}</small>
          </span>
          {canStart && startButton}
        </div>
      )}
      {past.length > 0 && (
        <Section title="Vụ đã kết thúc" icon="history" tone="sage" description={`${past.length} vụ trước trên thửa này`}>
          <div className="fw-seasons farmer-season-list">{past.map((s) => <SeasonRow key={s.id} season={s} plot={plot} past />)}</div>
        </Section>
      )}
      {!seasons.length && (
        <Section title="Mùa vụ" icon="history" tone="sage">
          <Empty
            icon="seeding"
            tone="leaf"
            title="Chưa có vụ canh tác"
            body={canStart
              ? 'Bạn đã có thửa ruộng. Bắt đầu vụ mới để ghi nhật ký, theo dõi hiệu suất và tính Carbon.'
              : 'Bạn chưa có quyền tạo vụ canh tác. Liên hệ chủ hộ hoặc cán bộ hợp tác xã để bắt đầu vụ trên thửa này.'}
            action={canStart ? startButton : undefined}
          />
        </Section>
      )}
      {seasons.length > 0 && !active && !past.length && (
        <Section title="Mùa vụ" icon="history" tone="sage">
          <div className="fw-seasons farmer-season-list">{seasons.map((s) => <SeasonRow key={s.id} season={s} plot={plot} />)}</div>
        </Section>
      )}
      {start.node}
    </>
  )
}
