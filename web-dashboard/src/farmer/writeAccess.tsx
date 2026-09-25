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

/** The one season status the journal accepts writes for. FastAPI's
 * `ActivityWriteService._write_batch` refuses every other status (a harvested,
 * closed, cancelled or merely planned season) with 422, so a button offered for
 * one of those could only fail. Exact match on purpose: the looser
 * `isActiveStatus` also accepts Vietnamese display labels and is for display. */
export const isJournalOpen = (status: string | null | undefined): boolean => status === 'active'

/** The season as a journal write target -- "Ghi hoạt động", edit, delete -- or
 * null when the farm role does not allow writing OR the season is not open.
 * No caller can turn a closed season into a write target by falling back to
 * it: the status is checked here, on the season actually passed in. */
export function useWritableSeason(ctx: { season: CropSeason; plot?: Plot | null } | null | undefined): SeasonContext | null {
  const canWrite = useCanWriteFarm()
  if (!ctx || !canWrite(ctx.plot?.farmId) || !isJournalOpen(ctx.season.status)) return null
  return toSeasonContext(ctx.season, ctx.plot)
}

/** May the viewer change the season record itself (its Carbon methodology
 * inputs)? Unlike the journal this does not depend on the status: FastAPI's
 * methodology route accepts a finished season, because correcting its water
 * regime and recalculating is a normal review action. */
export function useCanEditSeason(ctx: { season: CropSeason; plot?: Plot | null } | null | undefined): boolean {
  const canWrite = useCanWriteFarm()
  return Boolean(ctx) && canWrite(ctx!.plot?.farmId)
}
