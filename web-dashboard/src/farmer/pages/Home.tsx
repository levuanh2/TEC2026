import type { CurrentUser } from '../../api/me'
import type { Activity } from '../../types'
import { Link } from '../../ui'
import { greeting, localDay, longDay } from '../activityView'
import { useActivityMutations } from '../ActivityForms'
import type { QueryState } from '../data'
import { MiniTimeline } from '../journal'
import { Chip, Empty, ErrorPanel, Flash, MoreLink, Section, Sk, SkBlock } from '../kit'
import { CostPanel, PrimaryNextAction, SeasonContextBar, SummaryStrip, nextAction } from '../hybrid'
import { seasonFactsFromSummary } from '../metricsView'
import { useWritableSeason } from '../writeAccess'
import { NoActiveSeason } from '../StartSeason'
import { HOME_RECENT, primarySeason, useActivitySummary, useCarbonReadiness, useMetrics, useRecentActivities, useScope, type SeasonCtx } from '../scope'
import type { ActivitySummary } from '../../api/crops'

/** While the scope itself is loading, dependent sections are still "loading" too. */
function pending<T>(state: QueryState<T>, scopeLoading: boolean): QueryState<T> {
  return scopeLoading ? { ...state, loading: true } : state
}

/**
 * Farmer Home answers one question — what do I do next on this season — and
 * then gets out of the way. Four regions, in the farmer's reading order:
 *
 *   A. which season this is (one compact bar)
 *   B. ONE next action, decided from the server's state
 *   C. a compact read of the season (water · fertiliser · Carbon, then the
 *      journal count as a plain line), with direct cost in its own panel that
 *      says it is not a CO₂e input
 *   D. the last five activities, and a link to the whole journal
 *
 * Everything else has a home of its own and is not repeated here: recording
 * lives in the journal, resource and cost detail on Performance, Carbon repair
 * and results on Carbon, recommendations on the season page.
 */
export function FarmerHome({ viewer }: { viewer: CurrentUser }) {
  const scope = useScope()
  const primary = primarySeason(scope.data)
  const sid = primary?.season.id ?? null
  const metrics = useMetrics(sid)
  /* Home lists the newest records and reads the season's totals from the
   * server's summary — never the whole journal (Round 5.1): two small
   * requests whatever the number of records. */
  const activities = useRecentActivities(sid)
  const summary = useActivitySummary(sid)
  const carbonReadiness = useCarbonReadiness(sid)
  const mutations = useActivityMutations()
  const primaryWriteCtx = useWritableSeason(primary)
  const facts = seasonFactsFromSummary(summary.data, primary?.plot?.areaHa)
  const name = viewer.fullName?.trim()
  const action = nextAction({
    hasSeason: Boolean(sid),
    canWrite: Boolean(primaryWriteCtx),
    readiness: carbonReadiness.data,
    activities: activities.data,
    hasCarbonResult: metrics.data?.co2ePerKg != null,
  })
  const navigates = action?.kind === 'fix-data' || action?.kind === 'calculate' || action?.kind === 'view-result'

  return (
    <>
      <header className="fw-greet fw-greet--compact">
        <div>
          <p className="fw-greet__hello">{greeting()}{name ? `, ${name}` : ''}</p>
          <h1>Hôm nay trên ruộng của bạn</h1>
        </div>
        <div className="fw-greet__ctx">
          <Chip icon="calendar">{longDay(localDay(new Date()))}</Chip>
        </div>
      </header>
      <Flash message={mutations.flash} />

      <div className="fw-home-top">
        <HomeHero scope={scope} primary={primary} summary={summary.data} />
        <PrimaryNextAction
          loading={scope.loading || (Boolean(sid) && (activities.loading || summary.loading || carbonReadiness.loading || metrics.loading))}
          action={action}
          to={navigates ? '/farmer/carbon' : undefined}
          onAct={action?.kind === 'record' && primaryWriteCtx ? () => mutations.openPicker(primaryWriteCtx) : undefined}
        />
      </div>

      {sid && (
        <Section className="fw-area-summary" title="Tổng quan vụ này">
          <SummaryStrip activities={pending({ ...activities, loading: activities.loading || summary.loading }, scope.loading)} count={summary.data?.total ?? null} metrics={pending(metrics, scope.loading)} readiness={pending(carbonReadiness, scope.loading)} facts={facts} />
          <CostPanel metrics={pending(metrics, scope.loading)} facts={facts} moreTo="/farmer/performance" />
        </Section>
      )}

      {sid && (
        <Section className="fw-area-journal" title="Hoạt động gần đây" labelledBy="fw-home-recent" action={<MoreLink to="/farmer/journal">Xem toàn bộ nhật ký</MoreLink>}>
          <MiniTimeline state={pending(activities, scope.loading)} limit={HOME_RECENT} />
        </Section>
      )}
      {mutations.node}
    </>
  )
}

function HomeHero({ scope, primary, summary }: { scope: QueryState<{ farms: unknown[] }>; primary: SeasonCtx | null; summary?: ActivitySummary | null }) {
  if (scope.loading) return <HeroSkeleton />
  if (scope.error) return <ErrorPanel error={scope.error} onRetry={scope.reload} />
  if (!primary) return <NoActiveSeason purpose="home" />
  return <SeasonContextBar ctx={primary} journal={summary ? { firstSeedingAt: summary.firstSeedingAt, lastHarvestAt: summary.lastHarvestAt } : undefined} />
}

export function HeroSkeleton() {
  return (
    <SkBlock label="Đang tải vụ đang canh tác" className="fw-ctxbar">
      <Sk w={220} h={16} /><Sk w="55%" h={22} /><Sk w="42%" h={14} />
    </SkBlock>
  )
}
