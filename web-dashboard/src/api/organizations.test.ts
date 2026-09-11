import { afterEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken } from './client'
import { clearOrganizationCache, getOrganization, getOrganizationSummary } from './organizations'

const RAW_ORG = { id: 'org-1', organization_code: 'ORG-1', name: 'HTX Demo', organization_type: 'coop', is_active: true }

describe('getOrganization caching (brief Part B §20 — dedupe stable org identity, not business metrics)', () => {
  afterEach(() => { vi.unstubAllGlobals(); setAccessToken(null); clearOrganizationCache() })

  it('reuses one network call across repeated getOrganization(id) calls for the same org', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(RAW_ORG), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const [a, b, c] = await Promise.all([getOrganization('org-1'), getOrganization('org-1'), getOrganization('org-1')])
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(a).toEqual(b); expect(b).toEqual(c)
    expect(a.name).toBe('HTX Demo')
  })

  it('fetches again for a different organization id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(RAW_ORG), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await getOrganization('org-1')
    await getOrganization('org-2')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not cache a failed lookup', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { error: { code: 'not_found', message: 'no' } } }), { status: 404 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(RAW_ORG), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(getOrganization('org-1')).rejects.toBeTruthy()
    const org = await getOrganization('org-1')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(org.name).toBe('HTX Demo')
  })

  it('never caches organization summary — a live business rollup must always hit the network (brief Part B §18)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      organization_id: 'org-1', farm_count: 1, plot_count: 1, crop_season_count: 1, total_area_ha: 1,
      total_yield_kg: null, total_co2e_kg: null, co2e_per_kg: null,
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await getOrganizationSummary('org-1')
    await getOrganizationSummary('org-1')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
