// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { readViewerHint, toCurrentUser, writeViewerHint } from './me'

const base = { user_id: 'u-1', full_name: 'QA', roles: ['farmer'], organization_memberships: [{ organization_id: 'org-1' }] }

describe('toCurrentUser farm write access (B3)', () => {
  it('keeps only owner/editor farms as writable', () => {
    const user = toCurrentUser({
      ...base,
      roles: ['farmer', 'owner', 'viewer', 'editor'],
      farm_memberships: [
        { farm_id: 'farm-owner', farm_role: 'owner' },
        { farm_id: 'farm-viewer', farm_role: 'viewer' },
        { farm_id: 'farm-editor', farm_role: 'editor' },
      ],
    })
    expect(user.writableFarmIds).toEqual(['farm-owner', 'farm-editor'])
    expect(user.role).toBe('farmer')
  })

  it('a viewer-only farmer has no writable farm', () => {
    expect(toCurrentUser({ ...base, farm_memberships: [{ farm_id: 'f', farm_role: 'viewer' }] }).writableFarmIds).toEqual([])
    expect(toCurrentUser({ ...base }).writableFarmIds).toEqual([])
  })

  it('does not change role or organization resolution', () => {
    const user = toCurrentUser({ ...base, roles: ['cooperative_manager', 'farmer'] })
    expect(user.role).toBe('cooperative_manager')
    expect(user.organizationId).toBe('org-1')
  })
})

describe('viewer hint round-trip', () => {
  afterEach(() => localStorage.clear())

  it('keeps writable farms, and treats a hint without them as unknown', () => {
    writeViewerHint('u-1', { role: 'farmer', organizationId: 'org-1', fullName: 'QA', writableFarmIds: [] })
    expect(readViewerHint('u-1')?.writableFarmIds).toEqual([])
    localStorage.setItem('agricarbon.viewer.v1', JSON.stringify({ userId: 'u-1', role: 'farmer', organizationId: null }))
    expect(readViewerHint('u-1')?.writableFarmIds).toBeUndefined()
  })
})
