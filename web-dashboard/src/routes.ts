export type RouteName = 'login' | 'dashboard' | 'organizations' | 'farms' | 'farm' | 'plot' | 'season' | 'carbon' | 'activities' | 'mrv' | 'notFound'
export function routeName(path: string): RouteName {
  if (path === '/login') return 'login'; if (path === '/dashboard' || path === '/') return 'dashboard'; if (path === '/organizations') return 'organizations'; if (path === '/farms') return 'farms'; if (/^\/farms\/[^/]+$/.test(path)) return 'farm'; if (/^\/plots\/[^/]+$/.test(path)) return 'plot'; if (/^\/crop-seasons\/[^/]+\/carbon$/.test(path)) return 'carbon'; if (/^\/crop-seasons\/[^/]+\/activities$/.test(path)) return 'activities'; if (/^\/crop-seasons\/[^/]+$/.test(path)) return 'season'; if (path === '/mrv') return 'mrv'; return 'notFound'
}
