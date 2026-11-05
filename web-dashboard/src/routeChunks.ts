import { lazy, type ComponentType } from 'react'
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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const pick = <M, K extends keyof M>(load: () => Promise<M>, key: K) =>
  lazy(async () => ({ default: (await load())[key] as unknown as ComponentType<any> }))

export const OrganizationsPage = pick(loaders.directory, 'OrganizationsPage')
export const FarmsPage = pick(loaders.directory, 'FarmsPage')
export const FarmPage = pick(loaders.directory, 'FarmPage')
export const PlotPage = pick(loaders.directory, 'PlotPage')
export const FarmerAccountsPage = pick(loaders.farmers, 'FarmerAccountsPage')
export const ProvisionFarmerPage = pick(loaders.farmers, 'ProvisionFarmerPage')
export const PerformancePage = pick(loaders.performance, 'PerformancePage')
export const SeasonHub = pick(loaders.season, 'SeasonHub')
export const MrvPage = pick(loaders.mrv, 'MrvPage')
export const FarmerExperience = pick(loaders.farmer, 'FarmerExperience')

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
