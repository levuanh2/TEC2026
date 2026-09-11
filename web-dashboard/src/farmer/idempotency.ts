// Idempotency key lifecycle for one logical Quick Entry submission (brief §7/§8).
// A key is generated once per logical submission; a retry of the *same*
// submission must reuse it, never mint a fresh one — otherwise the backend's
// unique(recorded_by, web_idempotency_key) guard cannot deduplicate a retry.
export type IdempotencyEvent = 'open' | 'retry' | 'success' | 'close'

export function nextIdempotencyKey(
  current: string | null,
  event: IdempotencyEvent,
  generate: () => string = () => crypto.randomUUID(),
): string | null {
  switch (event) {
    case 'open':
      return generate()
    case 'retry':
      return current ?? generate()
    case 'success':
    case 'close':
      return null
  }
}
