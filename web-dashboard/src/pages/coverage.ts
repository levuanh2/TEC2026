import { useEffect, useState } from 'react'
import { getFarmCropSeasons, getPlotsForFarm, listFarms } from '../api/farms'
import { getResourceMetrics, type SeasonMetrics } from '../api/metrics'
import type { CropSeason, Plot } from '../types'

/* Which seasons stand behind a cooperative aggregate (Round 4.3).
 *
 * `/organizations/{id}/metrics` returns one figure per metric, and null as soon
 * as any season lacks the data — which is honest, but it never said how many
 * seasons that was, or which. There is no per-season rollup route, so this
 * composes the ones that exist (farms → seasons → each season's own
 * `/metrics`), the same way the operations queue does. Nothing is averaged or
 * recomputed here: a season either has the server's per-kg figure or it does
 * not, and the reason is read off the same response. */

export type AggregateKey = 'water' | 'fertilizer' | 'cost' | 'carbon'

export interface SeasonMetricRow {
  seasonId: string
  seasonName: string
  farmName: string
  plotName?: string
  metrics: SeasonMetrics | null
  error?: string
}

export interface MissingSeason { row: SeasonMetricRow; reason: string }

export interface Coverage {
  /** Seasons in scope, readable or not. */
  total: number
  /** Seasons whose own per-kg figure exists for this metric. */
  valid: number
  missing: MissingSeason[]
}

const PER_KG: Record<AggregateKey, keyof SeasonMetrics> = {
  water: 'waterPerKg', fertilizer: 'fertilizerPerKg', cost: 'costPerKg', carbon: 'co2ePerKg',
}

/** Why one season has no figure for this metric, in the words of what to record. */
export function missingReason(m: SeasonMetrics | null, key: AggregateKey, error?: string): string {
  if (!m) return error ? `Không đọc được dữ liệu vụ (${error})` : 'Không đọc được dữ liệu vụ'
  // Yield is the denominator of every per-kg figure; without it nothing resolves.
  if (key === 'carbon' && m.totalCo2eKg == null) return 'Chưa có kết quả Carbon'
  if (m.yieldKg == null) return 'Thiếu sản lượng thu hoạch'
  switch (key) {
    case 'water': return 'Thiếu lượng nước tưới'
    case 'fertilizer': return 'Thiếu khối lượng phân bón'
    case 'cost': return 'Có hoạt động chưa ghi chi phí'
    case 'carbon': return 'Thiếu sản lượng thu hoạch'
  }
}

export function coverageOf(rows: SeasonMetricRow[], key: AggregateKey): Coverage {
  const missing: MissingSeason[] = []
  let valid = 0
  for (const row of rows) {
    if (row.metrics && row.metrics[PER_KG[key]] != null) valid += 1
    else missing.push({ row, reason: missingReason(row.metrics, key, row.error) })
  }
  return { total: rows.length, valid, missing }
}

/** "Dựa trên 3/10 vụ đủ dữ liệu" — always said beside an aggregate. */
export const coverageLine = (c: Coverage) => `Dựa trên ${c.valid}/${c.total} vụ đủ dữ liệu`

export interface CoverageState { rows: SeasonMetricRow[]; loading: boolean; read: number; error: string | null }

const CONCURRENCY = 4

export function useSeasonCoverage(organizationId: string | null): CoverageState {
  const [state, setState] = useState<CoverageState>({ rows: [], loading: Boolean(organizationId), read: 0, error: null })
  useEffect(() => {
    if (!organizationId) { setState({ rows: [], loading: false, read: 0, error: null }); return }
    let live = true
    setState({ rows: [], loading: true, read: 0, error: null })
    void (async () => {
      try {
        // RLS scopes /v1/farms to what this manager may see — the same set the
        // organisation rollup is computed over.
        const farms = await listFarms()
        const perFarm = await Promise.all(farms.map(async (f) => {
          const [seasons, plots] = await Promise.all([
            getFarmCropSeasons(f.id).catch(() => [] as CropSeason[]),
            getPlotsForFarm(f.id).catch(() => [] as Plot[]),
          ])
          const plotName = new Map(plots.map((p) => [p.id, p.name]))
          return seasons.map((s): SeasonMetricRow => ({ seasonId: s.id, seasonName: s.name, farmName: f.name, plotName: plotName.get(s.plotId), metrics: null }))
        }))
        const rows = perFarm.flat()
        let read = 0
        let next = 0
        await Promise.all(Array.from({ length: Math.min(CONCURRENCY, rows.length) }, async () => {
          for (;;) {
            const i = next++
            if (i >= rows.length) return
            try { rows[i] = { ...rows[i], metrics: await getResourceMetrics(rows[i].seasonId) } }
            catch (e) { rows[i] = { ...rows[i], error: e instanceof Error ? e.message : 'lỗi không rõ' } }
            read += 1
            if (live) setState({ rows: [...rows], loading: read < rows.length, read, error: null })
          }
        }))
        if (live) setState({ rows: [...rows], loading: false, read: rows.length, error: null })
      } catch (e) {
        if (live) setState({ rows: [], loading: false, read: 0, error: e instanceof Error ? e.message : 'Không đọc được danh sách vụ.' })
      }
    })()
    return () => { live = false }
  }, [organizationId])
  return state
}
