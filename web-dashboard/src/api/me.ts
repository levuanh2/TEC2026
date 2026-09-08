import { apiRequest } from './client'
import type { Role } from '../types'

interface Membership { organization_id?: string }
interface MeResponse { roles: string[]; organization_memberships: Membership[] }

const rolePriority: Role[] = ['cooperative_manager', 'enterprise', 'regulator', 'farmer']

export interface CurrentUser { role: Role; organizationId: string | null }

export async function getMe(): Promise<CurrentUser> {
  const response = await apiRequest<MeResponse>('/v1/me')
  const role = rolePriority.find((candidate) => response.roles.includes(candidate)) ?? 'farmer'
  return { role, organizationId: response.organization_memberships[0]?.organization_id ?? null }
}
