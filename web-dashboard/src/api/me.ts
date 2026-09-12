import { apiRequest } from './client'
import type { Role } from '../types'

interface Membership { organization_id?: string }
interface MeResponse { user_id?: string; full_name?: string | null; roles: string[]; organization_memberships: Membership[] }

const rolePriority: Role[] = ['cooperative_manager', 'enterprise', 'regulator', 'farmer']

export interface CurrentUser { role: Role; organizationId: string | null; fullName?: string | null }

export async function getMe(): Promise<CurrentUser> {
  const response = await apiRequest<MeResponse>('/v1/me')
  const role = rolePriority.find((candidate) => response.roles.includes(candidate)) ?? 'farmer'
  return { role, organizationId: response.organization_memberships[0]?.organization_id ?? null, fullName: response.full_name ?? null }
}

/* Last resolved viewer for this signed-in user, so a refresh can paint the
 * right shell immediately while /v1/me revalidates. It is a routing hint
 * only — every data read is still authorized by the JWT + RLS — and is
 * ignored unless it belongs to the same Supabase user id. */
const VIEWER_HINT_KEY = 'agricarbon.viewer.v1'

export function readViewerHint(userId: string): CurrentUser | null {
  try {
    const raw = localStorage.getItem(VIEWER_HINT_KEY)
    if (!raw) return null
    const v = JSON.parse(raw) as { userId?: string; role?: string; organizationId?: string | null; fullName?: string | null }
    if (v.userId !== userId || !v.role || !rolePriority.includes(v.role as Role)) return null
    return { role: v.role as Role, organizationId: v.organizationId ?? null, fullName: v.fullName ?? null }
  } catch {
    return null
  }
}

export function writeViewerHint(userId: string, viewer: CurrentUser): void {
  try { localStorage.setItem(VIEWER_HINT_KEY, JSON.stringify({ userId, ...viewer })) } catch { /* storage unavailable */ }
}

export function clearViewerHint(): void {
  try { localStorage.removeItem(VIEWER_HINT_KEY) } catch { /* storage unavailable */ }
}
