// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { readViewerHint, toCurrentUser, writeViewerHint } from './me'

/* B2: the web understands the backend's canonical organization roles directly.
 * `enterprise_viewer` must reach the Management (read-only) shell, never the
 * Farmer shell and never become a cooperative manager. */

const me = (roles: string[]) => ({ user_id: 'u-1', full_name: 'QA', roles, organization_memberships: [{ organization_id: 'org-1' }] })
const shellFor = (role: string) => (role === 'farmer' ? 'farmer' : 'management')

describe('role resolution from /v1/me', () => {
  it.each([
    [['farmer', 'owner'], 'farmer'],
    [['cooperative_manager'], 'cooperative_manager'],
    [['enterprise_viewer'], 'enterprise_viewer'],
    [['regulator'], 'regulator'],
  ])('%j -> %s', (roles, role) => {
    expect(toCurrentUser(me(roles)).role).toBe(role)
  })

  it('enterprise_viewer enters the Management shell and is not a manager', () => {
    const user = toCurrentUser(me(['enterprise_viewer']))
    expect(shellFor(user.role)).toBe('management')
    expect(user.role).not.toBe('cooperative_manager')
  })

  it('a real hosted enterprise_viewer /v1/me shape maps to enterprise_viewer', () => {
    // Shape returned by hosted /v1/me for an enterprise viewer (no farm memberships).
    const user = toCurrentUser({
      user_id: 'u-2', full_name: null, roles: ['enterprise_viewer'],
      organization_memberships: [{ organization_id: 'org-ent' }], farm_memberships: [],
    })
    expect(user).toEqual({ role: 'enterprise_viewer', organizationId: 'org-ent', fullName: null, writableFarmIds: [] })
  })

  it('manager wins over other roles; the retired alias is not recognized', () => {
    expect(toCurrentUser(me(['enterprise_viewer', 'cooperative_manager'])).role).toBe('cooperative_manager')
    expect(toCurrentUser(me(['enterprise'])).role).toBe('farmer')
  })

  it('unknown or farm-only roles fall back to the Farmer shell', () => {
    expect(toCurrentUser(me([])).role).toBe('farmer')
    expect(toCurrentUser(me(['viewer'])).role).toBe('farmer')
    expect(toCurrentUser(me(['something_new'])).role).toBe('farmer')
  })
})

describe('viewer hint', () => {
  afterEach(() => localStorage.clear())

  it('accepts enterprise_viewer and ignores a hint saved with the retired alias', () => {
    writeViewerHint('u-1', { role: 'enterprise_viewer', organizationId: 'org-1' })
    expect(readViewerHint('u-1')?.role).toBe('enterprise_viewer')
    localStorage.setItem('agricarbon.viewer.v1', JSON.stringify({ userId: 'u-1', role: 'enterprise', organizationId: 'org-1' }))
    expect(readViewerHint('u-1')).toBeNull()
  })
})
