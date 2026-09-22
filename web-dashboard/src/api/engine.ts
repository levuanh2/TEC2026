import { apiRequest } from './client'

/** What the Carbon engine is running right now.
 *
 * Only used to tell a stored result apart from a current one: a calculation
 * carries the `ef_config_version` it was produced with, so a version that no
 * longer matches the engine means the number on screen predates the factor set
 * in use. Read once per session — it changes on deployment, not per season.
 */
export interface EngineInfo {
  efConfigVersion: string | null
  engineVersion: string | null
  carbonProductionReady: boolean
}

let cached: Promise<EngineInfo | null> | null = null

export function getEngineInfo(): Promise<EngineInfo | null> {
  cached ??= apiRequest<Record<string, unknown>>('/health')
    .then((h) => ({
      efConfigVersion: typeof h.ef_config_version === 'string' ? h.ef_config_version : null,
      engineVersion: typeof h.engine_version === 'string' ? h.engine_version : null,
      carbonProductionReady: h.carbon_production_ready === true,
    }))
    // Staleness is an enhancement, never a reason to fail a page: without the
    // engine's version the view model simply stops claiming a result is stale.
    .catch(() => null)
  return cached
}

/** Tests drive this module in isolation. */
export const resetEngineInfoCache = () => { cached = null }
