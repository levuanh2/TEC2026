import { createElement, lazy, type ComponentType } from 'react'
import { routeName } from './routes'

/* Route-level code splitting.
 *
 * Every page except the Management home (the operations queue) and the auth
 * screens is its own chunk. Login, session restore, the forced password change
 * and the app shell stay in the entry bundle: nothing on the way to signing in
 * may wait for a download.
 *
 * Each loader is memoised, so `prefetchRoute` (hover/focus on a link) and the
 * real navigation share one download.
 */

const once = <T,>(load: () => Promise<T>) => {
  let p: Promise<T> | null = null
  return () => {
    p ??= load().catch((e) => { p = null; throw e })
    return p
  }
}

export const loaders = {
  directory: once(() => import('./pages/directory')),
  farmers: once(() => import('./pages/farmers')),
  performance: once(() => import('./pages/performance')),
  season: once(() => import('./pages/season')),
  mrv: once(() => import('./pages/mrv')),
  farmer: once(() => import('./farmer/FarmerExperience')),
}

/* React.lazy remembers a rejected load for good, so a page whose chunk failed
 * once (network drop, file missing after a deployment) would fail forever in
 * this tab. Each route therefore keeps a replaceable lazy component: when its
 * load fails it registers itself here, and `retryFailedChunks` (the "Thử lại"
 * button of ChunkErrorBoundary) swaps in a fresh one, whose render calls the
 * loader again (`once` above already forgot the failed promise). */
const failedRoutes = new Set<() => void>()

export function retryFailedChunks(): void {
  const resets = [...failedRoutes]
  failedRoutes.clear()
  for (const reset of resets) reset()
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const lazyRoute = <M, K extends keyof M>(load: () => Promise<M>, key: K): ComponentType<any> => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const make = () => lazy(async () => {
    try {
      return { default: (await load())[key] as unknown as ComponentType<any> }
    } catch (e) {
      failedRoutes.add(reset)
      throw e
    }
  })
  let Current = make()
  const reset = () => { Current = make() }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const Route = (props: any) => createElement(Current, props)
  Route.displayName = `Route(${String(key)})`
  return Route
}

export const OrganizationsPage = lazyRoute(loaders.directory, 'OrganizationsPage')
export const FarmsPage = lazyRoute(loaders.directory, 'FarmsPage')
export const FarmPage = lazyRoute(loaders.directory, 'FarmPage')
export const PlotPage = lazyRoute(loaders.directory, 'PlotPage')
export const FarmerAccountsPage = lazyRoute(loaders.farmers, 'FarmerAccountsPage')
export const ProvisionFarmerPage = lazyRoute(loaders.farmers, 'ProvisionFarmerPage')
export const PerformancePage = lazyRoute(loaders.performance, 'PerformancePage')
export const SeasonHub = lazyRoute(loaders.season, 'SeasonHub')
export const MrvPage = lazyRoute(loaders.mrv, 'MrvPage')
export const FarmerExperience = lazyRoute(loaders.farmer, 'FarmerExperience')

/** Which chunk a path needs (null: it is in the entry bundle). */
export function chunkFor(path: string): (() => Promise<unknown>) | null {
  if (path.startsWith('/farmer')) return loaders.farmer
  switch (routeName(path.split('?')[0])) {
    case 'organizations': case 'farms': case 'farm': case 'plot': return loaders.directory
    case 'farmer-accounts': case 'farmer-account-new': return loaders.farmers
    case 'performance': return loaders.performance
    case 'season': case 'activities': case 'season-performance': case 'season-mrv': case 'carbon': return loaders.season
    case 'mrv': return loaders.mrv
    default: return null
  }
}

/** Start downloading a route's code before the click (hover/focus on a link).
 *  Failures are ignored here — the navigation itself retries and reports. */
export function prefetchRoute(path: string): void {
  void chunkFor(path)?.().catch(() => undefined)
}
