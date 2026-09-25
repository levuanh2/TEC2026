export type RouteName =
  | 'login'
  | 'dashboard'
  | 'organizations'
  | 'performance'
  | 'farms'
  | 'farmer-accounts'
  | 'farmer-account-new'
  | 'seasons'
  | 'data-gaps'
  | 'ops-carbon'
  | 'farm'
  | 'plot'
  | 'season'
  | 'season-performance'
  | 'season-mrv'
  | 'carbon'
  | 'activities'
  | 'mrv'
  | 'farmer'
  | 'notFound'

export function routeName(path: string): RouteName {
  if (path === '/farmer' || path.startsWith('/farmer/')) return 'farmer'
  if (path === '/login') return 'login'
  if (path === '/dashboard' || path === '/') return 'dashboard'
  if (path === '/organizations') return 'organizations'
  if (path === '/performance') return 'performance'
  if (path === '/farms') return 'farms'
  // Not under /farmer: that prefix belongs to the Farmer experience and the
  // role redirect sends a manager away from anything starting with it.
  if (path === '/accounts/farmers') return 'farmer-accounts'
  if (path === '/accounts/farmers/new') return 'farmer-account-new'
  // Management entry points into the season workspace. The per-season URLs
  // (/crop-seasons/:id/...) are unchanged and still resolve below.
  if (path === '/seasons') return 'seasons'
  if (path === '/data-gaps') return 'data-gaps'
  if (path === '/carbon') return 'ops-carbon'
  if (/^\/farms\/[^/]+$/.test(path)) return 'farm'
  if (/^\/plots\/[^/]+$/.test(path)) return 'plot'
  if (/^\/crop-seasons\/[^/]+\/carbon$/.test(path)) return 'carbon'
  if (/^\/crop-seasons\/[^/]+\/activities$/.test(path)) return 'activities'
  if (/^\/crop-seasons\/[^/]+\/performance$/.test(path)) return 'season-performance'
  if (/^\/crop-seasons\/[^/]+\/mrv$/.test(path)) return 'season-mrv'
  if (/^\/crop-seasons\/[^/]+$/.test(path)) return 'season'
  if (path === '/mrv') return 'mrv'
  return 'notFound'
}

/** Extract the :id segment for a hierarchy route, or null. */
export function routeParam(path: string): string | null {
  const m = path.match(/^\/(?:farms|plots|crop-seasons)\/([^/]+)/)
  return m ? m[1] : null
}
