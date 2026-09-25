import type { Role } from './types'

// Route paths a role may see in navigation. This is a UI affordance only — the
// backend RLS is the real authorization boundary (brief §20, FR-1c-03).
const MANAGER_ROUTES = ['/dashboard', '/farms', '/seasons', '/data-gaps', '/carbon', '/mrv', '/organizations', '/performance']
// This helper feeds the legacy Management shell only. Authenticated farmers
// are routed into the separate FarmerExperience shell, whose navigation lives
// alongside that shell rather than inside the Management sidebar.
const FARMER_ROUTES = ['/dashboard', '/farms']
// Provisioning farmer accounts is the cooperative manager's alone
// (`private.user_is_org_manager`); enterprise viewers and regulators read.
const PROVISIONING_ROUTES = ['/accounts/farmers']

export function visibleNav(role: Role): string[] {
  if (role === 'farmer') return FARMER_ROUTES
  return role === 'cooperative_manager' ? [...MANAGER_ROUTES, ...PROVISIONING_ROUTES] : MANAGER_ROUTES
}
