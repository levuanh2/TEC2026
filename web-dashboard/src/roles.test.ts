import { describe, expect, it } from 'vitest'
import { visibleNav } from './roles'
describe('role-aware navigation', () => { it('hides manager reporting from a farmer without treating that as authorization', () => { expect(visibleNav('farmer')).not.toContain('/mrv'); expect(visibleNav('cooperative_manager')).toContain('/mrv') }) })
