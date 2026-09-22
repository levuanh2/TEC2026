import { useEffect, useState } from 'react'
import { getCarbon, getCarbonReadiness, type CarbonResult } from '../api/carbon'
import { getEngineInfo } from '../api/engine'
import { carbonView, type CarbonView } from './readiness'

/* One season's Carbon state, read the same way by every screen that shows it.
 *
 * Management's season hub, its Carbon tab and the Farmer screens all render
 * from this, so "đã đủ dữ liệu" on one tab and "thiếu tỷ lệ chất khô của rơm"
 * on another can no longer describe the same season.
 */
export interface CarbonViewState {
  view: CarbonView | null
  result: CarbonResult | null
  loading: boolean
  /** The readiness read itself failed — distinct from "no calculation yet". */
  error: string | null
  reload: () => void
}

export function useCarbonView(seasonId: string | null, opts: {
  /** Latest moment a Carbon input was written, when the caller knows it. */
  latestInputAt?: string | null
  fixTarget?: string | null
  resultTarget?: string | null
} = {}): CarbonViewState {
  const { latestInputAt = null, fixTarget = null, resultTarget = null } = opts
  const [state, setState] = useState<{ view: CarbonView | null; result: CarbonResult | null; loading: boolean; error: string | null }>({
    view: null, result: null, loading: Boolean(seasonId), error: null,
  })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!seasonId) { setState({ view: null, result: null, loading: false, error: null }); return }
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    void (async () => {
      try {
        const [readiness, engine] = await Promise.all([getCarbonReadiness(seasonId), getEngineInfo()])
        // A 404 here is the documented "chưa từng tính" answer, not a failure.
        const result = await getCarbon(seasonId).catch(() => null)
        if (!alive) return
        setState({
          view: carbonView({
            readiness, result,
            liveEfConfigVersion: engine?.efConfigVersion ?? null,
            latestInputAt, fixTarget, resultTarget,
          }),
          result, loading: false, error: null,
        })
      } catch (e) {
        if (!alive) return
        setState({ view: null, result: null, loading: false, error: e instanceof Error ? e.message : 'Không đọc được trạng thái Carbon.' })
      }
    })()
    return () => { alive = false }
  }, [seasonId, latestInputAt, fixTarget, resultTarget, tick])

  return { ...state, reload: () => setTick((t) => t + 1) }
}
