import { describe, expect, it } from 'vitest'
import { routeName } from './routes'
describe('dashboard routes', () => {
  it('recognizes authorized crop routes', () => { expect(routeName('/crop-seasons/abc/carbon')).toBe('carbon'); expect(routeName('/crop-seasons/abc/activities')).toBe('activities') })
  it('rejects an unknown route', () => { expect(routeName('/not-a-route')).toBe('notFound') })
  it('keeps Farmer routes distinct from Management routes', () => {
    expect(routeName('/farmer')).toBe('farmer')
    expect(routeName('/farmer/crop-seasons/abc/carbon')).toBe('farmer')
  })
})
