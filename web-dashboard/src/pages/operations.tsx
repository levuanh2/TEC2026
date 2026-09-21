import { useMemo, useState } from 'react'
import { Ico } from '../icons'
import { go, Link } from '../ui'
import { exceptionsOf, useOperations, type Exception, type OpsRow, type Severity } from './ops'
import { label } from '../vocab'

/* Management is an operations workspace: the queue of work comes first, a
 * summary second, and there is no chart on this page. Every row is something
 * a cooperative officer can act on, with the action next to it.
 */

const SEVERITY: Record<Severity, { label: string; role: string; icon: 'warning' | 'info' | 'clock' }> = {
  high: { label: 'Cao', role: 'error', icon: 'warning' },
  medium: { label: 'Trung bình', role: 'attention', icon: 'clock' },
  low: { label: 'Thấp', role: 'info', icon: 'info' },
}

/* Wording comes from the shared view model's five states, so this table, the
 * dashboard queue, the season Carbon tab and the Farmer screens cannot drift
 * apart again. `methodology` is the lavender information tint, never green. */
const CARBON_LABEL: Record<OpsRow['carbon'], { text: string; role: string }> = {
  calculated: { text: 'Đã tính', role: 'positive' },
  stale: { text: 'Cần tính lại', role: 'attention' },
  // Mint, not the completed green: "có thể tính" and "đã tính" must not read
  // as the same state at a glance.
  ready: { text: 'Sẵn sàng tính', role: 'water' },
  missing_data: { text: 'Thiếu dữ liệu', role: 'attention' },
  methodology_limited: { text: 'Giới hạn hệ số', role: 'methodology' },
  unknown: { text: '—', role: 'neutral' },
}

const DATA_LABEL: Record<OpsRow['data'], { text: string; role: string }> = {
  complete: { text: 'Đủ dữ liệu', role: 'positive' },
  missing: { text: 'Thiếu dữ liệu', role: 'attention' },
  unknown: { text: '—', role: 'neutral' },
}

/** Data completeness, phrased so it can never contradict the Carbon column:
 *  a season whose only blocker is an unverified factor has complete *data*,
 *  and the badge says so together with the limitation. */
function dataBadge(r: OpsRow): { text: string; role: string } {
  if (r.data === 'complete' && r.limitations.length) return { text: 'Đủ · vướng hệ số', role: 'methodology' }
  return DATA_LABEL[r.data]
}

function Sk({ w, h = 20 }: { w: number | string; h?: number }) {
  return <span className="skeleton" style={{ display: 'inline-block', width: w, height: h, borderRadius: 6 }} aria-hidden="true" />
}

function Badge({ role, children, icon }: { role: string; children: React.ReactNode; icon?: 'warning' | 'info' | 'clock' | 'check' }) {
  return <span className={`ops-badge role--${role}`}>{icon && <Ico name={icon} size={13} />}{children}</span>
}

/** `/dashboard` — "Hôm nay cần xử lý gì?" */
export function OperationsOverview({ organizationId }: { organizationId: string | null }) {
  const ops = useOperations(organizationId)
  const rows = ops.data?.rows ?? []
  const queue = useMemo(() => exceptionsOf(rows), [rows])
  const counts = {
    missing: rows.filter((r) => r.missing.length).length,
    ready: rows.filter((r) => r.carbon === 'ready').length,
    stale: rows.filter((r) => r.carbon === 'stale').length,
    // 'verified'/'closed' are the settled case statuses (see exceptionsOf).
    mrv: rows.filter((r) => r.mrv && r.mrv.status !== 'verified' && r.mrv.status !== 'closed').length,
    limited: rows.filter((r) => r.carbon === 'methodology_limited').length,
  }

  return (
    <section className="ops">
      <header className="ops__head">
        <div>
          <h1>Hôm nay cần xử lý gì?</h1>
          <p className="ops__sub">Toàn bộ việc cần chú ý của hợp tác xã, xếp theo mức độ.</p>
        </div>
        {organizationId && (
          <button type="button" className="btn btn--ghost" onClick={ops.reload} disabled={ops.loading}>
            <Ico name="refresh" size={14} />{ops.loading ? 'Đang tải…' : 'Tải lại'}
          </button>
        )}
      </header>

      {/* The page keeps its heading without an organisation: a screen with no
        * h1 is a screen a screen-reader user cannot place. */}
      {!organizationId ? (
        <div className="state">
          <p className="state__title">Chưa gắn với hợp tác xã nào</p>
          <p className="state__body">Tài khoản này chưa thuộc tổ chức nào nên chưa có việc cần xử lý.</p>
        </div>
      ) : (
        <>

      <div className="ops-sum">
        {summaryTiles(counts, ops.loading).map((t) => (
          <SumTile key={t.label} {...t} loading={ops.loading} />
        ))}
      </div>

      {ops.error && <p className="ops-error" role="alert"><Ico name="warning" size={14} />{ops.error}</p>}

      <h2 className="ops__section">Danh sách công việc ưu tiên</h2>
      {ops.data?.pending ? (
        <p className="ops-note" aria-live="polite"><Ico name="refresh" size={13} />Đang đọc {ops.data.pending} vụ — danh sách hiện dần.</p>
      ) : null}
      {ops.loading && !queue.length ? (
        <p className="ops-note">Đang đọc dữ liệu từng vụ…</p>
      ) : queue.length === 0 && !ops.data?.pending ? (
        <p className="ops-note"><Ico name="check" size={14} />Không có việc nào cần xử lý lúc này.</p>
      ) : (
        <ExceptionTable queue={queue} />
      )}
        </>
      )}
    </section>
  )
}

type TileIcon = 'warning' | 'leaf' | 'mrv' | 'info' | 'clock'
interface Tile { role: string; icon: TileIcon; value: number; label: string; to: string }

/** Which summary cards are worth a place.
 *
 * While the read is still running every card shows, so the row does not
 * reflow under the officer's cursor. Once it has finished, a card standing at
 * zero is not work — it drops out rather than competing with the ones that
 * are. If nothing is outstanding at all, the queue's own "không có việc nào"
 * says so and no cards are needed. */
function summaryTiles(counts: { missing: number; ready: number; stale: number; mrv: number; limited: number }, loading: boolean): Tile[] {
  const all: Tile[] = [
    { role: 'attention', icon: 'warning', value: counts.missing, label: 'Vụ thiếu dữ liệu', to: '/data-gaps?loc=missing' },
    { role: 'water', icon: 'leaf', value: counts.ready, label: 'Sẵn sàng tính Carbon', to: '/carbon?loc=ready' },
    { role: 'attention', icon: 'clock', value: counts.stale, label: 'Kết quả cần tính lại', to: '/carbon?loc=stale' },
    { role: 'info', icon: 'mrv', value: counts.mrv, label: 'Hồ sơ MRV chờ xử lý', to: '/mrv' },
    { role: 'methodology', icon: 'info', value: counts.limited, label: 'Vướng giới hạn hệ số', to: '/carbon?loc=methodology_limited' },
  ]
  return loading ? all : all.filter((t) => t.value > 0)
}

function SumTile({ role, icon, value, label, to, loading }: Tile & { loading: boolean }) {
  return (
    <Link to={to} className={`ops-sum__tile role--${role}`}>
      <span className="ops-sum__ico" aria-hidden="true"><Ico name={icon} size={16} /></span>
      {/* Never "…" as a resting value: a skeleton reads as "still coming". */}
      {loading ? <Sk w={34} h={26} /> : <b>{value}</b>}
      <span>{label}</span>
    </Link>
  )
}

function ExceptionTable({ queue }: { queue: Exception[] }) {
  return (
    <div className="ops-table__wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th scope="col">Mức độ</th>
            <th scope="col">Nông hộ</th>
            <th scope="col">Thửa / Vụ mùa</th>
            <th scope="col">Vấn đề</th>
            <th scope="col">Hành động</th>
          </tr>
        </thead>
        <tbody>
          {queue.map((e) => {
            const sev = SEVERITY[e.severity]
            return (
              <tr key={e.id}>
                <td data-label="Mức độ"><Badge role={sev.role} icon={sev.icon}>{sev.label}</Badge></td>
                <td data-label="Nông hộ">
                  <b>{e.row.farmName}</b>
                  {e.row.farmCode && <small>{e.row.farmCode}</small>}
                </td>
                <td data-label="Thửa / Vụ mùa">
                  {/* Two seasons of one farm can share a season code; without
                    * the plot an officer cannot tell these rows apart. */}
                  <b>{e.row.plotName ?? 'Chưa rõ thửa'}</b>
                  <small>{e.row.seasonName} · {e.row.statusLabel}</small>
                </td>
                <td data-label="Vấn đề">
                  <b>{e.issue}</b>
                  {e.detail && <small>{e.detail}</small>}
                </td>
                <td data-label="Hành động">
                  <Link to={e.action.to} className="btn btn--ghost btn--sm">{e.action.label}</Link>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export type SeasonsFocus = 'all' | 'missing' | 'carbon'

const FOCUS_COPY: Record<SeasonsFocus, { title: string; sub: string }> = {
  all: { title: 'Danh sách nông hộ và vụ mùa', sub: 'Tìm kiếm, lọc và theo dõi tiến độ dữ liệu, Carbon, MRV.' },
  missing: { title: 'Dữ liệu còn thiếu', sub: 'Các vụ chưa đủ dữ liệu để tính phát thải — bấm Xử lý để mở đúng vụ.' },
  carbon: { title: 'Carbon theo vụ', sub: 'Trạng thái tính phát thải của từng vụ trong hợp tác xã.' },
}

/** `/seasons`, `/data-gaps`, `/carbon` — one dense table, three entry points. */
export function SeasonsWorkspace({ organizationId, focus = 'all' }: { organizationId: string | null; focus?: SeasonsFocus }) {
  const ops = useOperations(organizationId)
  // A summary card links to its own filtered view, so the number a person
  // clicked and the list they land on are the same set.
  const preset = new URLSearchParams(location.search).get('loc')
  const [q, setQ] = useState('')
  const [dataFilter, setDataFilter] = useState<'all' | OpsRow['data']>(
    preset === 'missing' || focus === 'missing' ? 'missing' : 'all')
  const [carbonFilter, setCarbonFilter] = useState<'all' | OpsRow['carbon']>(
    preset && preset !== 'missing' ? (preset as OpsRow['carbon']) : 'all')
  const [mrvFilter, setMrvFilter] = useState<'all' | 'has' | 'none'>('all')
  const [selected, setSelected] = useState<string | null>(null)

  const rows = ops.data?.rows ?? []
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return rows.filter((r) => {
      if (needle && !`${r.farmName} ${r.farmCode ?? ''} ${r.plotName ?? ''} ${r.plotCode ?? ''} ${r.seasonName}`.toLowerCase().includes(needle)) return false
      if (dataFilter !== 'all' && r.data !== dataFilter) return false
      if (carbonFilter !== 'all' && r.carbon !== carbonFilter) return false
      if (mrvFilter === 'has' && !r.mrv) return false
      if (mrvFilter === 'none' && r.mrv) return false
      if (focus === 'carbon' && r.carbon === 'unknown') return false
      return true
    })
  }, [rows, q, dataFilter, carbonFilter, mrvFilter, focus])
  const current = filtered.find((r) => r.seasonId === selected) ?? null
  const copy = FOCUS_COPY[focus]

  return (
    <section className="ops">
      <header className="ops__head">
        <div>
          <h1>{copy.title}</h1>
          <p className="ops__sub">{copy.sub}</p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={ops.reload} disabled={ops.loading}>
          <Ico name="refresh" size={14} />{ops.loading ? 'Đang tải…' : 'Tải lại'}
        </button>
      </header>

      <div className="ops-filters" role="search">
        <label className="ops-search">
          <Ico name="search" size={14} />
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm nông hộ, vụ mùa…" aria-label="Tìm nông hộ hoặc vụ mùa" />
        </label>
        <label className="ops-filter">
          <span>Dữ liệu</span>
          <select value={dataFilter} onChange={(e) => setDataFilter(e.target.value as typeof dataFilter)}>
            <option value="all">Tất cả</option>
            <option value="missing">Thiếu dữ liệu</option>
            <option value="complete">Đủ dữ liệu</option>
          </select>
        </label>
        <label className="ops-filter">
          <span>Carbon</span>
          <select value={carbonFilter} onChange={(e) => setCarbonFilter(e.target.value as typeof carbonFilter)}>
            <option value="all">Tất cả</option>
            <option value="missing_data">Thiếu dữ liệu</option>
            <option value="methodology_limited">Giới hạn hệ số</option>
            <option value="ready">Sẵn sàng tính</option>
            <option value="calculated">Đã tính</option>
            <option value="stale">Cần tính lại</option>
          </select>
        </label>
        <label className="ops-filter">
          <span>MRV</span>
          <select value={mrvFilter} onChange={(e) => setMrvFilter(e.target.value as typeof mrvFilter)}>
            <option value="all">Tất cả</option>
            <option value="has">Có hồ sơ</option>
            <option value="none">Chưa có hồ sơ</option>
          </select>
        </label>
        <p className="ops-count" aria-live="polite">
          {filtered.length} vụ{ops.data?.pending ? ` · đang đọc thêm ${ops.data.pending}` : ''}
        </p>
      </div>

      {ops.error && <p className="ops-error" role="alert"><Ico name="warning" size={14} />{ops.error}</p>}

      <div className={`ops-split${current ? ' is-open' : ''}`}>
        <div className="ops-table__wrap">
          <table className="ops-table ops-table--seasons">
            <thead>
              <tr>
                <th scope="col">Nông hộ</th>
                <th scope="col">Thửa</th>
                <th scope="col">Vụ mùa</th>
                <th scope="col">Dữ liệu</th>
                <th scope="col">Carbon</th>
                <th scope="col">MRV</th>
                <th scope="col">Hành động</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const data = dataBadge(r)
                const carbon = CARBON_LABEL[r.carbon]
                // One interaction, not two near-identical ones: the row (and
                // its single button) opens the detail panel; the panel itself
                // carries the one link that leaves the list.
                const open = () => setSelected(r.seasonId)
                return (
                  <tr key={r.seasonId} aria-selected={r.seasonId === selected}>
                    <td data-label="Nông hộ"><b>{r.farmName}</b>{r.farmCode && <small>{r.farmCode}</small>}</td>
                    <td data-label="Thửa">
                      {/* Without this column two seasons of one farm sharing a
                        * season code render as identical rows (audit P0-2). */}
                      <b>{r.plotName ?? 'Chưa rõ thửa'}</b>{r.plotCode && <small>{r.plotCode}</small>}
                    </td>
                    <td data-label="Vụ mùa"><b>{r.seasonName}</b><small>{r.statusLabel}</small></td>
                    <td data-label="Dữ liệu">
                      {r.loading ? <Sk w={86} h={20} /> : <Badge role={data.role}>{data.text}</Badge>}
                      {!r.loading && r.missing.length > 0 && <small>{r.missing.length} mục</small>}
                    </td>
                    <td data-label="Carbon">{r.loading ? <Sk w={92} h={20} /> : <Badge role={carbon.role}>{carbon.text}</Badge>}</td>
                    <td data-label="MRV">{r.mrv ? <Badge role="info">{r.mrv.caseCode}</Badge> : <span className="ops-dash">—</span>}</td>
                    <td data-label="Hành động">
                      <button
                        type="button" className="btn btn--ghost btn--sm"
                        onClick={open}
                        aria-expanded={r.seasonId === selected}
                        aria-label={`Chi tiết vụ ${r.seasonName}, thửa ${r.plotName ?? r.plotId}, ${r.farmName}`}
                      >Chi tiết</button>
                    </td>
                  </tr>
                )
              })}
              {/* Three distinct states, never one blank table: still reading,
                * nothing matched the filter, or nothing to show at all. */}
              {!filtered.length && ops.loading && (
                <tr><td colSpan={7} className="ops-empty" aria-live="polite">
                  <p>Đang đọc danh sách vụ…</p>
                  <Sk w={180} h={14} />
                </td></tr>
              )}
              {!filtered.length && !ops.loading && (
                <tr><td colSpan={7} className="ops-empty">
                  <p>{rows.length ? 'Không có vụ nào khớp bộ lọc.' : 'Chưa có vụ nào trong phạm vi này.'}</p>
                  {rows.length > 0 && (
                    <button
                      type="button" className="btn btn--ghost btn--sm"
                      onClick={() => { setQ(''); setDataFilter('all'); setCarbonFilter('all'); setMrvFilter('all') }}
                    >Xóa bộ lọc</button>
                  )}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        {current && <SeasonDetailPanel row={current} onClose={() => setSelected(null)} />}
      </div>
    </section>
  )
}

function SeasonDetailPanel({ row, onClose }: { row: OpsRow; onClose: () => void }) {
  const carbon = CARBON_LABEL[row.carbon]
  return (
    <aside className="ops-detail" aria-label={`Chi tiết vụ ${row.seasonName}`}>
      <header>
        <div>
          <b>{row.seasonName}</b>
          <small>
            {row.farmName}{row.farmCode ? ` · ${row.farmCode}` : ''}
            {' · '}{row.plotName ?? 'Chưa rõ thửa'}{row.plotCode ? ` (${row.plotCode})` : ''}
            {' · '}{row.statusLabel}
          </small>
        </div>
        <button type="button" className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Đóng chi tiết">Đóng</button>
      </header>

      {row.loading && <p className="ops-note" aria-live="polite">Đang đọc dữ liệu của vụ này…</p>}

      <section>
        <h3>Dữ liệu còn thiếu</h3>
        {row.loading
          ? <p className="ops-note">Chưa đọc xong.</p>
          : row.missing.length === 0
            ? <p className="ops-note"><Ico name="check" size={13} />Không thiếu dữ liệu người dùng nhập được.</p>
            : <ul className="ops-list">{row.missing.map((m) => <li key={m.code}><b>{m.label}</b><small>{m.detail}</small></li>)}</ul>}
      </section>

      <section>
        <h3>Carbon</h3>
        <p>{row.loading ? <Sk w={92} /> : <Badge role={carbon.role}>{carbon.text}</Badge>}</p>
        {!row.loading && row.view && <p className="ops-note">{row.view.detail}</p>}
        {row.carbonPerKg != null && <p className="ops-note">{row.carbonPerKg} kg CO₂e / kg lúa</p>}
        {row.limitations.map((m) => (
          <p key={m.code} className="ops-limit role--methodology"><Ico name="info" size={13} /><span><b>{m.label}</b> — {m.detail}</span></p>
        ))}
      </section>

      <section>
        <h3>MRV</h3>
        {row.mrv
          ? <p><Badge role="info">{row.mrv.caseCode}</Badge> <span className="ops-note">Trạng thái: {label('mrvCaseStatus', row.mrv.status)}</span></p>
          : <p className="ops-note">Vụ này chưa thuộc hồ sơ MRV nào.</p>}
      </section>

      <footer>
        <Link to={`/crop-seasons/${row.seasonId}`} className="btn btn--sm">Mở vụ mùa</Link>
        <Link to={`/crop-seasons/${row.seasonId}/carbon`} className="btn btn--ghost btn--sm">Xem Carbon</Link>
        <Link to={`/farms/${row.farmId}`} className="btn btn--ghost btn--sm">Hồ sơ nông hộ</Link>
      </footer>
    </aside>
  )
}
