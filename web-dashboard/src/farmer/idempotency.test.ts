import { describe, expect, it } from 'vitest'
import { nextIdempotencyKey } from './idempotency'

describe('idempotency key lifecycle', () => {
  it('mints a fresh key when a form opens', () => {
    let n = 0
    const gen = () => `key-${++n}`
    expect(nextIdempotencyKey(null, 'open', gen)).toBe('key-1')
  })

  it('reuses the same key across a retry of the same logical submission', () => {
    let n = 0
    const gen = () => `key-${++n}`
    const opened = nextIdempotencyKey(null, 'open', gen)
    expect(nextIdempotencyKey(opened, 'retry', gen)).toBe(opened)
    expect(nextIdempotencyKey(opened, 'retry', gen)).toBe(opened)
  })

  it('mints a key on retry if none exists yet', () => {
    let n = 0
    const gen = () => `key-${++n}`
    expect(nextIdempotencyKey(null, 'retry', gen)).toBe('key-1')
  })

  it('clears the key after success so the next open mints a new one', () => {
    let n = 0
    const gen = () => `key-${++n}`
    const opened = nextIdempotencyKey(null, 'open', gen)
    const cleared = nextIdempotencyKey(opened, 'success', gen)
    expect(cleared).toBeNull()
    const reopened = nextIdempotencyKey(cleared, 'open', gen)
    expect(reopened).not.toBe(opened)
  })

  it('clears the key on close (a new logical submission gets a new key)', () => {
    const opened = nextIdempotencyKey(null, 'open', () => 'key-a')
    expect(nextIdempotencyKey(opened, 'close')).toBeNull()
  })
})
