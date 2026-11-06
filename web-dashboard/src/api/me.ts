import { apiRequest } from './client'
import type { Role } from '../types'

interface Membership { organization_id?: string; role?: string }
interface FarmMembership { farm_id?: string; farm_role?: string }
interface MeResponse { user_id?: string; full_name?: string | null; roles: string[]; organization_memberships: Membership[]; farm_memberships?: FarmMembership[]; must_change_password?: boolean }

// Canonical backend role names (`organization_role` enum). A user with none of
// them falls back to the Farmer shell, whose data is still RLS-scoped and whose
// writes the server authorizes; a hint carrying a retired alias is ignored.
const rolePriority: Role[] = ['cooperative_manager', 'enterprise_viewer', 'regulator', 'farmer']
const WRITE_FARM_ROLES = new Set(['owner', 'editor'])

/** `writableFarmIds`: farms where the caller's `farm_role` allows journal
 *  writes (owner/editor). Only drives which write buttons the Farmer UI shows —
 *  FastAPI and RLS enforce the rule. Absent = not known yet. */
export interface CurrentUser { role: Role; organizationId: string | null; fullName?: string | null; writableFarmIds?: string[]
  /** The account /v1/me answered for (absent in hints and mocks). */
  userId?: string
  /** Live server flag: the account still has its temporary password. */
  mustChangePassword?: boolean
  /** Everything /v1/me said this account may reach: each active organisation
   *  membership (`org:<id>:<role>`) and each farm role (`farm:<id>:<role>`,
   *  read-only ones included), sorted. Not shown anywhere; the shell compares
   *  it between answers, so that losing any of them (a read-only farm too)
   *  drops what was cached under it. Never written to the hint. */
  access?: string[] }

/** See `CurrentUser.access`. */
export function accessOf(response: Pick<MeResponse, 'organization_memberships' | 'farm_memberships' | 'roles'>): string[] {
  const orgs = (response.organization_memberships ?? []).map((m) => `org:${m.organization_id ?? '?'}:${m.role ?? '?'}`)
  const farms = (response.farm_memberships ?? []).map((m) => `farm:${m.farm_id ?? '?'}:${m.farm_role ?? '?'}`)
  const roles = [...(response.roles ?? [])].map((r) => `role:${r}`)
  return [...new Set([...orgs, ...farms, ...roles])].sort()
}

export function toCurrentUser(response: MeResponse): CurrentUser {
  const role = rolePriority.find((candidate) => response.roles.includes(candidate)) ?? 'farmer'
  const writableFarmIds = (response.farm_memberships ?? [])
    .filter((m) => m.farm_id && m.farm_role && WRITE_FARM_ROLES.has(m.farm_role))
    .map((m) => m.farm_id as string)
  return {
    access: accessOf(response),
    role,
    organizationId: response.organization_memberships[0]?.organization_id ?? null,
    fullName: response.full_name ?? null,
    writableFarmIds,
    // Present only when set, so every normal account keeps the same shape.
    ...(response.must_change_password === true ? { mustChangePassword: true } : {}),
    ...(response.user_id ? { userId: response.user_id } : {}),
  }
}

export async function getMe(): Promise<CurrentUser> {
  return toCurrentUser(await apiRequest<MeResponse>('/v1/me'))
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
    const v = JSON.parse(raw) as { userId?: string; role?: string; organizationId?: string | null; fullName?: string | null; writableFarmIds?: unknown }
    if (v.userId !== userId || !v.role || !rolePriority.includes(v.role as Role)) return null
    const writableFarmIds = Array.isArray(v.writableFarmIds) && v.writableFarmIds.every((x) => typeof x === 'string')
      ? v.writableFarmIds as string[]
      : undefined
    return { role: v.role as Role, organizationId: v.organizationId ?? null, fullName: v.fullName ?? null, writableFarmIds }
  } catch {
    return null
  }
}

export function writeViewerHint(userId: string, viewer: CurrentUser): void {
  // `access` is a comparison key for this tab, not a routing hint: kept out of storage.
  const { access: _access, ...hint } = viewer
  try { localStorage.setItem(VIEWER_HINT_KEY, JSON.stringify({ userId, ...hint })) } catch { /* storage unavailable */ }
}

export function clearViewerHint(): void {
  try { localStorage.removeItem(VIEWER_HINT_KEY) } catch { /* storage unavailable */ }
}
