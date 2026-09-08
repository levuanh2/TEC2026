import type { Role } from './types'
const managerRoutes = ['/dashboard', '/organizations', '/farms', '/plots/plot-demo-01', '/crop-seasons/crop-demo-01', '/crop-seasons/crop-demo-01/carbon', '/mrv']
export function visibleNav(role: Role): string[] { return role === 'farmer' ? ['/dashboard', '/crop-seasons/crop-demo-01', '/crop-seasons/crop-demo-01/activities'] : managerRoutes }
