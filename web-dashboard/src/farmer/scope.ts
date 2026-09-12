import { useEffect, useState } from 'react'
import type { CropSeason, Farm, Plot } from '../types'
import { ApiError } from '../api/client'
import { getFarmerScope, usingMockData, type FarmerScope } from '../api/farms'
import { getActivities } from '../api/crops'
import { getResourceMetrics } from '../api/metrics'
import { generateRecommendations, getRecommendations, type Recommendation } from '../api/recommendations'
import { getCvInferences } from '../api/cv'
import { getCarbon, type CarbonResult } from '../api/carbon'
import { clearSeasonDataChanged, fetchQuery, keys, peekQuery, prefetchQuery, seasonDataChanged, setQueryData, STABLE_MS, useQuery, type QueryState } from './data'

export type SeasonCtx = { season: CropSeason; plot?: Plot; farm?: Farm }

export const isActiveStatus = (status: string | null | undefined) => /(^active$|đang|canh tác)/i.test(status ?? '')

export function seasonStatusLabel(status: string | null | undefined): string {
  const s = (status ?? '').toLowerCase()
  if (isActiveStatus(s)) return 'Đang canh tác'
  if (/harvest|complete|closed|done/.test(s)) return 'Đã kết thúc'
  if (/plan|draft/.test(s)) return 'Kế hoạch'
  return status || 'Chưa rõ trạng thái'
}

const byPlantingDesc = (a: CropSeason, b: CropSeason) => String(b.plantingDate ?? '').localeCompare(String(a.plantingDate ?? ''))

export function resolveSeason(scope: FarmerScope | undefined, seasonId: string | null): SeasonCtx | null {
  if (!scope || !seasonId) return null
  const season = scope.seasons.find((s) => s.id === seasonId)
  if (!season) return null
  const plot = scope.plots.find((p) => p.id === season.plotId)
  return { season, plot, farm: scope.farms.find((f) => f.id === plot?.farmId) }
}

/** Active seasons first, then most recently planted. */
export function seasonsOf(scope: FarmerScope | undefined): SeasonCtx[] {
  if (!scope) return []
  return [...scope.seasons]
    .sort((a, b) => Number(isActiveStatus(b.status)) - Number(isActiveStatus(a.status)) || byPlantingDesc(a, b))
    .map((s) => resolveSeason(scope, s.id)!)
}

export const activeSeasonsOf = (scope: FarmerScope | undefined) => seasonsOf(scope).filter((c) => isActiveStatus(c.season.status))
export const primarySeason = (scope: FarmerScope | undefined): SeasonCtx | null => activeSeasonsOf(scope)[0] ?? null
export const plotsOfFarm = (scope: FarmerScope, farmId: string) => scope.plots.filter((p) => p.farmId === farmId)
export const seasonsOfPlot = (scope: FarmerScope, plotId: string) => scope.seasons.filter((s) => s.plotId === plotId).sort(byPlantingDesc)
export const seasonsOfPlots = (scope: FarmerScope, plots: Plot[]) => scope.seasons.filter((s) => plots.some((p) => p.id === s.plotId)).sort(byPlantingDesc)

/** Sum of recorded plot areas; null when any plot has no area (never a partial total). */
export function sumArea(plots: Plot[]): number | null {
  if (!plots.length || plots.some((p) => p.areaHa == null)) return null
  return plots.reduce((total, p) => total + Number(p.areaHa), 0)
}

export const placeOf = (farm: Farm) => [farm.commune, farm.district, farm.province].filter(Boolean).join(', ')

/* ------------------------------------------------------------ hooks */

export const useScope = () => useQuery(keys.scope, getFarmerScope, STABLE_MS)
export const useMetrics = (id: string | null) => useQuery(id ? keys.metrics(id) : null, () => getResourceMetrics(id!))
export const useActivities = (id: string | null) => useQuery(id ? keys.activities(id) : null, () => getActivities(id!))
export const useCvHistory = (id: string | null) => useQuery(id ? keys.cv(id) : null, () => getCvInferences(id!))

/* M05 generation is a deliberate non-blocker.
 *
 * `POST .../recommendations/generate` re-runs the rule engine and the Carbon
 * Engine: measured 7.3-9.5s and 33 Supabase round trips against hosted
 * Supabase, which alone accounted for ~7s of Home's and Season's time to full
 * content. A page therefore only ever GETs what is already stored; generation
 * runs when the farmer asks for it, or on its own AFTER the page is usable and
 * only when the stored set is actually out of date. It never blocks, and a
 * failure leaves the stored recommendations on screen (never a page error). */

/** A stored set older than this is refreshed once, in the background. */
export const RECS_STALE_AFTER_MS = 6 * 60 * 60_000
/** How long after the section renders the background refresh may start. */
const RECS_DEFER_MS = 1_200

/** Whether a stored set should be regenerated at all (§ deferred generation):
 *  the season's records changed in this session, nothing is stored yet, or what
 *  is stored has aged past `RECS_STALE_AFTER_MS`. Anything else renders as-is —
 *  a page load must not pay for generation just because it happened. */
export function recommendationsOutOfDate(seasonId: string, items: Recommendation[]): boolean {
  if (seasonDataChanged(seasonId)) return true
  if (!items.length) return true
  const newest = items.reduce((max, r) => (r.generatedAt > max ? r.generatedAt : max), '')
  const at = Date.parse(newest)
  return Number.isNaN(at) || Date.now() - at > RECS_STALE_AFTER_MS
}

export interface RecommendationsState extends QueryState<Recommendation[]> {
  /** A generation run is in flight (stored items stay visible meanwhile). */
  generating: boolean
  /** The last run failed; stored items, if any, are still valid. */
  generateError?: string
  /** Explicit "Cập nhật khuyến nghị" — always runs, even if not out of date. */
  regenerate: () => void
}

export function useRecommendations(id: string | null): RecommendationsState {
  const list = useQuery(id ? keys.recs(id) : null, () => getRecommendations(id!))

  const run = async () => {
    const items = await generateRecommendations(id!)
    clearSeasonDataChanged(id!)
    setQueryData(keys.recs(id!), items)
    return items.length
  }

  // Armed only after the section has rendered its stored data and the deferral
  // has elapsed, so generation can never be part of first load.
  const due = Boolean(id) && list.data !== undefined && recommendationsOutOfDate(id!, list.data ?? [])
  const [armed, setArmed] = useState(false)
  useEffect(() => {
    if (!due) { setArmed(false); return }
    const timer = setTimeout(() => setArmed(true), RECS_DEFER_MS)
    return () => clearTimeout(timer)
  }, [due, id])

  const gen = useQuery(id ? keys.recsGen(id) : null, run, STABLE_MS, armed)
  return {
    ...list,
    generating: Boolean(id) && (gen.loading || gen.refreshing),
    generateError: gen.error,
    regenerate: () => { if (id) fetchQuery(keys.recsGen(id), run, { force: true }).catch(() => undefined) },
  }
}

export type CarbonState = { kind: 'result'; result: CarbonResult } | { kind: 'none'; reason: 'no_calculation' | null }

export const useCarbon = (id: string | null) => useQuery<CarbonState>(id ? keys.carbon(id) : null, async () => {
  if (usingMockData) return { kind: 'none', reason: null }
  try {
    return { kind: 'result', result: await getCarbon(id!) }
  } catch (err) {
    if (err instanceof ApiError && err.code === 'no_calculation') return { kind: 'none', reason: 'no_calculation' }
    throw err
  }
})

/* ---------------------------------------------------------- prefetch */

/** Bounded warm-up on nav hover/focus: at most scope + one season read per target. */
export function prefetchNav(to: string): void {
  prefetchQuery(keys.scope, getFarmerScope, STABLE_MS)
  const season = primarySeason(peekQuery<FarmerScope>(keys.scope))?.season
  if (!season) return
  if (to === '/farmer' || to === '/farmer/journal') prefetchQuery(keys.activities(season.id), () => getActivities(season.id))
  if (to === '/farmer' || to === '/farmer/performance') prefetchQuery(keys.metrics(season.id), () => getResourceMetrics(season.id))
}

export function prefetchSeason(seasonId: string): void {
  prefetchQuery(keys.metrics(seasonId), () => getResourceMetrics(seasonId))
  prefetchQuery(keys.activities(seasonId), () => getActivities(seasonId))
}
