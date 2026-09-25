// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { SeasonMetrics } from '../api/metrics'
import type { Activity } from '../types'
import { AggregateBasis, AggregateMetric } from '../components/AggregateMetric'
import type { FarmPerformance } from '../api/organizations'
import { coverageOf } from '../pages/coverage'
import type { QueryState } from './data'
import { CostPanel, SummaryStrip } from './hybrid'
import { MetricRow } from './metricRows'
import { JUDGEMENT_WORDS, metricDetails, seasonFacts } from './metricsView'

/* Round 4.3 — what the rendered metrics say, and what they never say. */

afterEach(cleanup)

const q = <T,>(data: T): QueryState<T> => ({ data, loading: false, error: null, reload: () => {} } as unknown as QueryState<T>)
const metrics = (over: Partial<SeasonMetrics> = {}): SeasonMetrics => ({
  yieldKg: 5200, waterM3: 330, fertilizerKg: 150, totalCo2eKg: null,
  waterPerKg: 330 / 5200, fertilizerPerKg: 150 / 5200, co2ePerKg: null, costPerKg: null,
  completeness: { water: true, fertilizer: true, cost: false, carbon: false }, ...over,
})
const acts = (n: number): Activity[] => Array.from({ length: n }, (_, i) => ({
  id: `a${i}`, cropSeasonId: 's', occurredAt: '2026-09-01T00:00:00Z', type: 'irrigation', detail: JSON.stringify({ water_volume_m3: 10 }), recorder: '', source: 'web',
}))

describe('Farmer Home summary', () => {
  it('the activity count is a neutral journal line with its link, never a positive tile', () => {
    const { container } = render(<SummaryStrip activities={q(acts(9))} metrics={q(metrics())} readiness={q(null)} facts={seasonFacts(acts(9), 1.3)} />)
    expect(screen.getByText('Nhật ký: 9 hoạt động đã ghi')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Xem nhật ký/ }).getAttribute('href')).toBe('/farmer/journal')
    const line = screen.getByText('Nhật ký: 9 hoạt động đã ghi').closest('p')!
    expect(line.className).not.toMatch(/fw-role/)
    // No tile at all carries the healthy tone: a reading is not a grade.
    expect(container.querySelector('.fw-role--positive')).toBeNull()
    expect(screen.queryByText('Hoạt động đã ghi')).toBeNull()
  })

  it('shows the easy unit with one sentence and "Xem chi tiết"', () => {
    render(<SummaryStrip activities={q(acts(1))} metrics={q(metrics())} readiness={q(null)} facts={seasonFacts([], 1.3)} />)
    expect(screen.getByText('63')).toBeTruthy()
    expect(screen.getByText('lít nước / kg lúa')).toBeTruthy()
    expect(screen.getAllByRole('link', { name: /Xem chi tiết/ }).length).toBeGreaterThan(0)
  })

  it('cost with no data reads "Chưa đủ dữ liệu chi phí" and offers the journal, never 0 ₫', () => {
    const { container } = render(<CostPanel metrics={q(metrics({ completeness: { water: true, fertilizer: true, cost: true, carbon: false } }))} facts={seasonFacts([], null)} moreTo="/farmer/performance" />)
    expect(screen.getByText('Chưa đủ dữ liệu chi phí')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Bổ sung chi phí trong Nhật ký/ })).toBeTruthy()
    expect(container.textContent).not.toMatch(/(^|\D)0 ₫/)
  })
})

describe('Performance metric row', () => {
  const water = metricDetails(metrics(), seasonFacts([], 1.3))[0]

  it('value and unit are one unbreakable reading', () => {
    const { container } = render(<MetricRow d={water} season={null} />)
    const reading = container.querySelector('.fw-mrow__value .fw-reading')!
    expect(reading.textContent).toBe('63 lít nước / kg lúa')
  })

  it('says what it means, what it was computed from, and that there is no benchmark', () => {
    render(<MetricRow d={water} season={null} />)
    expect(screen.getByText('Tính từ 330 m³ nước và 5.200 kg thóc đã ghi.')).toBeTruthy()
    expect(screen.getByText('Chưa có mốc để đánh giá cao hay thấp.')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Xem hoạt động tưới/ }).getAttribute('href')).toBe('/farmer/journal?loai=irrigation')
  })

  it('the methodology disclosure exposes aria-expanded and toggles', () => {
    render(<MetricRow d={water} season={null} />)
    const btn = screen.getByRole('button', { name: /Cách tính và dữ liệu sử dụng/ })
    expect(btn.getAttribute('aria-expanded')).toBe('false')
    const body = document.getElementById(btn.getAttribute('aria-controls')!)!
    expect(body.hidden).toBe(true)
    fireEvent.click(btn)
    expect(btn.getAttribute('aria-expanded')).toBe('true')
    expect(body.hidden).toBe(false)
  })

  it('the status is words and an icon, not colour alone; no judgement word is rendered', () => {
    const { container } = render(<>{metricDetails(metrics({ costPerKg: 170 }), seasonFacts([], 1.3)).map((d) => <MetricRow key={d.key} d={d} season={null} />)}</>)
    expect(screen.getAllByText('Đủ dữ liệu để tính').length).toBe(2)
    const text = container.textContent!.toLowerCase()
    for (const w of JUDGEMENT_WORDS) expect(text).not.toContain(w)
  })

  it('a missing metric renders a sentence, not 0', () => {
    const d = metricDetails(metrics({ yieldKg: null, waterPerKg: null, fertilizerPerKg: null }), seasonFacts([], null))[0]
    const { container } = render(<MetricRow d={d} season={null} />)
    expect(container.querySelector('.fw-metric__empty')!.textContent).toMatch(/Chưa đủ dữ liệu/)
    expect(container.querySelector('.fw-mrow__value')).toBeNull()
  })

  it('cost and Carbon rows carry different semantic groups', () => {
    const ds = metricDetails(metrics(), seasonFacts([], null))
    const { container } = render(<>{ds.map((d) => <MetricRow key={d.key} d={d} season={null} />)}</>)
    expect(container.querySelector('[data-metric="cost"]')!.className).toContain('fw-mrow--cost')
    expect(container.querySelector('[data-metric="carbon"]')!.className).toContain('fw-mrow--carbon')
  })
})

describe('Management aggregate', () => {
  const farms: FarmPerformance[] = Array.from({ length: 10 }, (_, i) => ({
    farmId: `f${i}`, farmName: `Hộ ${i}`, areaHa: 2, yieldKg: i < 3 ? 5000 : null,
    waterPerKg: i < 3 ? 0.06 : null, fertilizerPerKg: null, co2ePerKg: null, costPerKg: null, dataStatus: 'partial',
  }))

  it('always states coverage, and "N nông hộ thiếu dữ liệu" opens exactly those farms', () => {
    render(<AggregateMetric name="Nước / kg thóc" value={null} unit="m³/kg" formula="f" coverage={coverageOf(farms, 'water')}  />)
    // Round 4.4 wording: one sentence, cause included.
    expect(screen.getByTestId('aggregate-coverage').textContent).toBe('Chưa công bố chỉ số toàn HTX — mới có 3/10 nông hộ đủ dữ liệu.')
    const toggle = screen.getByRole('button', { name: /7 nông hộ thiếu dữ liệu/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect((document.getElementById(toggle.getAttribute('aria-controls')!) as HTMLElement).hidden).toBe(true)
    fireEvent.click(toggle)
    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(7)
    expect(links.map((a) => a.getAttribute('href'))).toEqual(farms.slice(3).map((f) => `/farms/${f.farmId}`))
    // Round 4.4: the benchmark line is said once for the page (AggregateBasis).
    cleanup(); render(<AggregateBasis scope="HTX · 10 nông hộ" />)
    expect(screen.getByText(/^Chưa có mốc so sánh/)).toBeTruthy()
  })

  it('never shows a season count it cannot derive — it says coverage is per farm', () => {
    render(<><AggregateBasis scope="s" /><AggregateMetric name="x" value={null} unit="u" formula="f" coverage={coverageOf(farms, 'water')} /></>)
    // Round 4.4: the per-season gap is stated in user terms, not "endpoint".
    expect(screen.getByTestId('aggregate-season-coverage').textContent).toBe('Tính theo nông hộ; chưa có tổng hợp chi tiết theo từng vụ.')
    expect(document.body.textContent).not.toMatch(/\d+\/\d+ vụ/)
  })

  it('a computed aggregate still says what it is based on', () => {
    const all = farms.map((f) => ({ ...f, yieldKg: 5000, waterPerKg: 0.06 }))
    render(<AggregateMetric name="Nước / kg thóc" value="0,063" unit="m³/kg" formula="f" coverage={coverageOf(all, 'water')}  />)
    expect(screen.getByTestId('aggregate-coverage').textContent).toBe('Tính trên 10/10 nông hộ đủ dữ liệu.')
    expect(screen.queryByRole('button', { name: /thiếu dữ liệu/ })).toBeNull()
  })

  it('while the farm rows load, it says so instead of implying full coverage', () => {
    render(<AggregateMetric name="x" value="1" unit="u" formula="f" coverage={null} loadingCoverage />)
    expect(screen.getByTestId('aggregate-coverage').textContent).toMatch(/Đang đọc độ phủ dữ liệu/)
  })
})
