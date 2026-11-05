import { getOrganizationCarbonStatus } from '../api/carbon'
import { getEngineInfo } from '../api/engine'
import { getOrganizationPlotsSeasons, listFarms } from '../api/farms'
import { getOrganizationMrvBatches } from '../api/mrv'
import { getFarmPerformance, getOrganizationMetrics } from '../api/organizations'
import { routeName } from '../routes'
import { keys, METADATA_STALE_MS, queryClient } from './client'

/* Data prefetch on link intent (hover/focus). `prefetchQuery` does nothing
 * while an entry is fresh and joins a request already in flight, so a hover
 * never duplicates a read; it only starts a stale/missing one a few hundred
 * milliseconds before the click. Only the organisation-wide reads a route
 * needs at the top of the page are prefetched — never a per-row fan-out. */

const opsReads = (org: string) => [
  queryClient.prefetchQuery({ queryKey: keys.farms(), queryFn: () => listFarms() }),
  queryClient.prefetchQuery({ queryKey: keys.org(org, 'plots-seasons'), queryFn: () => getOrganizationPlotsSeasons(org) }),
  queryClient.prefetchQuery({ queryKey: keys.org(org, 'carbon-status'), queryFn: () => getOrganizationCarbonStatus(org) }),
  queryClient.prefetchQuery({ queryKey: keys.org(org, 'mrv-batches'), queryFn: () => getOrganizationMrvBatches(org) }),
  queryClient.prefetchQuery({ queryKey: keys.engine(), queryFn: () => getEngineInfo(), staleTime: METADATA_STALE_MS }),
]

export function prefetchRouteData(path: string, organizationId: string | null): void {
  if (!organizationId) return
  switch (routeName(path.split('?')[0])) {
    case 'dashboard': case 'seasons': case 'data-gaps': case 'ops-carbon':
      void Promise.all(opsReads(organizationId))
      return
    case 'farms':
      void queryClient.prefetchQuery({ queryKey: keys.farms(), queryFn: () => listFarms() })
      void queryClient.prefetchQuery({ queryKey: keys.org(organizationId, 'plots-seasons'), queryFn: () => getOrganizationPlotsSeasons(organizationId) })
      return
    case 'performance':
      void queryClient.prefetchQuery({ queryKey: keys.org(organizationId, 'metrics'), queryFn: () => getOrganizationMetrics(organizationId) })
      void queryClient.prefetchQuery({ queryKey: keys.org(organizationId, 'farm-performance'), queryFn: () => getFarmPerformance(organizationId) })
      return
    default:
  }
}
