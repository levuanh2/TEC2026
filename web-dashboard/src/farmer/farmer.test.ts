import { describe, expect, it } from 'vitest'
import { routeName } from '../routes'

describe('Farmer information architecture', () => {
  it('keeps Farmer destinations distinct from Management route names', () => {
    expect(routeName('/farmer')).toBe('farmer')
    expect(routeName('/farmer/farms/farm-1')).toBe('farmer')
    expect(routeName('/farmer/crop-seasons/season-1/carbon')).toBe('farmer')
  })
})
