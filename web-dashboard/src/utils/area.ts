/** A farm's area is the sum of its plots' recorded areas — the same rule the
 *  server's organisation rollup uses (`read_repo.py`, farm-performance
 *  `area_ha`). `/v1/farms` carries no area, so the farm register and the farm
 *  page both derive it here, from the plots, and cannot disagree.
 *
 *  A plot with no recorded area is not counted as zero: the total is then
 *  marked incomplete instead of silently understating the farm. */
export interface FarmArea { ha: number | null; complete: boolean; plots: number }

export function farmArea(plots: readonly { areaHa?: number | null }[]): FarmArea {
  const known = plots.map((p) => p.areaHa).filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
  return {
    ha: known.length ? known.reduce((s, v) => s + v, 0) : null,
    complete: known.length === plots.length,
    plots: plots.length,
  }
}
