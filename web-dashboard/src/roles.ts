import type { Role } from './types'

// Route paths a role may see in navigation. This is a UI affordance only — the
// backend RLS is the real authorization boundary (brief §20, FR-1c-03).
const MANAGER_ROUTES = ['/dashboard', '/organizations', '/farms', '/performance', '/mrv']
// This helper feeds the legacy Management shell only. Authenticated farmers
// are routed into the separate FarmerExperience shell, whose navigation lives
// alongside that shell rather than inside the Management sidebar.
const FARMER_ROUTES = ['/dashboard', '/farms']

export function visibleNav(role: Role): string[] {
  return role === 'farmer' ? FARMER_ROUTES : MANAGER_ROUTES
}
