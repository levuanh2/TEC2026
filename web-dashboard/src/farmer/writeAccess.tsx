import { createContext, useContext } from 'react'
import type { CropSeason, Plot } from '../types'
import { toSeasonContext, type SeasonContext } from './ActivityForms'

/* Which farms the signed-in farmer may write to (farm_role owner/editor), from
 * /v1/me. This only decides whether journal write buttons are shown: a farm
 * `viewer` would be refused by FastAPI and by RLS anyway, so offering them a
 * form that can only fail is the bug being avoided here, not the security
 * boundary. `undefined` means "not known yet" and keeps today's behaviour. */
export const FarmWriteAccess = createContext<readonly string[] | undefined>(undefined)

export function canWriteFarm(writableFarmIds: readonly string[] | undefined, farmId: string | null | undefined): boolean {
  if (writableFarmIds === undefined) return true
  return Boolean(farmId) && writableFarmIds.includes(farmId as string)
}

export function useCanWriteFarm(): (farmId: string | null | undefined) => boolean {
  const writable = useContext(FarmWriteAccess)
  return (farmId) => canWriteFarm(writable, farmId)
}

/** The season as a write target, or null when the farmer may not write to it. */
export function useWritableSeason(ctx: { season: CropSeason; plot?: Plot | null } | null | undefined): SeasonContext | null {
  const canWrite = useCanWriteFarm()
  if (!ctx || !canWrite(ctx.plot?.farmId)) return null
  return toSeasonContext(ctx.season, ctx.plot)
}
