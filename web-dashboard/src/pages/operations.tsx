import { useMemo, useState } from 'react'
import { Ico } from '../icons'
import { Link, SideDrawer } from '../ui'
import { exceptionsOf, useOperations, type Exception, type OpsRow, type Severity } from './ops'
import { label } from '../vocab'
import { perKg as perKgFmt } from '../format'

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

      {/* The counts above are work items, each tile opening exactly the
        * seasons it counts; this line says what they were counted over. */}
      {!ops.loading && rows.length > 0 && (
        <p className="ops-scope" data-testid="ops-scope">
          Phạm vi: toàn HTX · {rows.length} vụ · mỗi ô mở đúng danh sách vụ được đếm. Đây là số việc cần xử lý, không phải điểm hiệu suất.
        </p>
      )}

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

const FOCUS_COPY: Record<SeasonsFocus, { title: string; sub: string; search: string }> = {
  all: {
    title: 'Vụ mùa',
    sub: 'Toàn bộ vụ trong phạm vi hợp tác xã — giai đoạn, trạng thái và ngày của từng vụ.',
    search: 'Tìm nông hộ, thửa hoặc vụ…',
  },
  missing: {
    title: 'Dữ liệu còn thiếu',
    sub: 'Các vụ còn thông tin có thể bổ sung để tính phát thải — bấm Xử lý để xem đúng mục cần nhập.',
    search: 'Tìm vụ cần bổ sung…',
  },
  carbon: {
    title: 'Carbon theo vụ',
    sub: 'Tính toán và kết quả phát thải của từng vụ: sẵn sàng hay chưa, kết quả còn mới hay đã cũ.',
    search: 'Tìm vụ theo nông hộ, thửa…',
  },
}

/** The one action a Carbon row permits, from the shared view model's state. */
function carbonRowAction(r: OpsRow): { label: string; to: string } | null {
  const tab = `/crop-seasons/${r.seasonId}/carbon`
  switch (r.carbon) {
    case 'missing_data': return { label: 'Bổ sung dữ liệu', to: `/crop-seasons/${r.seasonId}` }
    case 'ready': return { label: 'Tính Carbon', to: tab }
    case 'stale': return { label: 'Tính lại', to: tab }
    case 'calculated': return { label: 'Xem kết quả', to: tab }
    case 'methodology_limited': return { label: 'Xem giới hạn', to: tab }
    default: return null
  }
}

const nf = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 })
const shortDate = (iso?: string) => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : null)

/**
 * `/seasons`, `/data-gaps`, `/carbon` — one data source, three jobs.
 *
 * They used to be the same table under three headings. Each now has its own
 * default set, columns, row emphasis, empty state and primary action:
 *   /seasons    every season, lifecycle columns (stage, dates), open detail
 *   /data-gaps  only seasons with user-fixable gaps, what is missing, "Xử lý"
 *   /carbon     readiness, result, freshness, totals, the action the state allows
 * No owner, deadline or figure is shown that the server did not return.
 */
export function SeasonsWorkspace({ organizationId, focus = 'all' }: { organizationId: string | null; focus?: SeasonsFocus }) {
  const ops = useOperations(organizationId)
  const preset = new URLSearchParams(location.search).get('loc')
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<string>('all')
  const [carbonFilter, setCarbonFilter] = useState<'all' | OpsRow['carbon']>(
    preset && preset !== 'missing' ? (preset as OpsRow['carbon']) : 'all')
  const [includeComplete, setIncludeComplete] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)

  const rows = ops.data?.rows ?? []
  const statuses = useMemo(() => [...new Map(rows.map((r) => [r.status ?? '', r.statusLabel])).entries()].filter(([k]) => k), [rows])
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return rows.filter((r) => {
      if (needle && !`${r.farmName} ${r.farmCode ?? ''} ${r.plotName ?? ''} ${r.plotCode ?? ''} ${r.seasonName}`.toLowerCase().includes(needle)) return false
      if (focus === 'all' && status !== 'all' && r.status !== status) return false
      // Data gaps: a season is on this list because a person can fix it. A
      // season blocked only by an unverified factor is not — it lives on /carbon.
      if (focus === 'missing' && !includeComplete && !r.loading && !r.missing.length) return false
      if (focus === 'carbon' && carbonFilter !== 'all' && r.carbon !== carbonFilter) return false
      return true
    })
  }, [rows, q, status, carbonFilter, includeComplete, focus])
  const current = rows.find((r) => r.seasonId === selected) ?? null
  const copy = FOCUS_COPY[focus]
  const limitedOnly = rows.filter((r) => !r.loading && !r.missing.length && r.limitations.length).length
  const cols = focus === 'all' ? 8 : focus === 'missing' ? 7 : 6

  return (
    <section className={`ops ops--${focus}`}>
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
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={copy.search} aria-label="Tìm nông hộ hoặc vụ mùa" />
        </label>
        {focus === 'all' && (
          <label className="ops-filter">
            <span>Trạng thái vụ</span>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="all">Tất cả</option>
              {statuses.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        )}
        {focus === 'missing' && (
          <label className="ops-check">
            <input type="checkbox" checked={includeComplete} onChange={(e) => setIncludeComplete(e.target.checked)} />
            <span>Hiện cả vụ đã đủ dữ liệu</span>
          </label>
        )}
        {focus === 'carbon' && (
          <label className="ops-filter">
            <span>Trạng thái Carbon</span>
            <select value={carbonFilter} onChange={(e) => setCarbonFilter(e.target.value as typeof carbonFilter)}>
              <option value="all">Tất cả</option>
              <option value="missing_data">Thiếu dữ liệu</option>
              <option value="methodology_limited">Giới hạn hệ số</option>
              <option value="ready">Sẵn sàng tính</option>
              <option value="calculated">Đã tính</option>
              <option value="stale">Cần tính lại</option>
            </select>
          </label>
        )}
        <p className="ops-count" aria-live="polite">
          {filtered.length} vụ{ops.data?.pending ? ` · đang đọc thêm ${ops.data.pending}` : ''}
        </p>
      </div>

      {ops.error && <p className="ops-error" role="alert"><Ico name="warning" size={14} />{ops.error}</p>}

      <div className="ops-table__wrap">
        <table className={`ops-table ops-table--seasons ops-table--${focus}`}>
          <thead>
            <tr>
              <th scope="col">Nông hộ</th>
              <th scope="col">Thửa</th>
              <th scope="col">Vụ</th>
              {focus === 'all' && <>
                <th scope="col">Giai đoạn</th>
                <th scope="col">Gieo sạ</th>
                <th scope="col">Thu hoạch</th>
                <th scope="col">Carbon</th>
              </>}
              {focus === 'missing' && <>
                <th scope="col" className="num">Cần bổ sung</th>
                <th scope="col">Thông tin còn thiếu</th>
                <th scope="col">Carbon</th>
              </>}
              {focus === 'carbon' && <>
                <th scope="col">Trạng thái Carbon</th>
                <th scope="col">Cần xử lý · Kết quả</th>
              </>}
              <th scope="col"><span className="sr-only">Hành động</span></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <SeasonRow key={r.seasonId} r={r} focus={focus} selected={r.seasonId === selected} onOpen={() => setSelected(r.seasonId)} />
            ))}
            {!filtered.length && (ops.loading || ops.data?.pending) ? (
              <tr><td colSpan={cols} className="ops-empty" aria-live="polite">
                <p>Đang đọc danh sách vụ…</p>
                <Sk w={180} h={14} />
              </td></tr>
            ) : null}
            {!filtered.length && !ops.loading && !ops.data?.pending && (
              <tr><td colSpan={cols} className="ops-empty">
                <EmptyCopy focus={focus} hasRows={rows.length > 0} limitedOnly={limitedOnly} />
                {q.trim() !== '' && <button type="button" className="btn btn--ghost btn--sm" onClick={() => setQ('')}>Xóa bộ lọc</button>}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {current && (
        <SideDrawer
          label={`Chi tiết vụ ${current.seasonName}, ${current.plotName ?? ''}`}
          onClose={() => setSelected(null)}
          initialFocus={current.missing.length ? '[data-drawer-missing]' : undefined}
        >
          <SeasonDetailPanel row={current} focus={focus} onClose={() => setSelected(null)} />
        </SideDrawer>
      )}
    </section>
  )
}

function EmptyCopy({ focus, hasRows, limitedOnly }: { focus: SeasonsFocus; hasRows: boolean; limitedOnly: number }) {
  if (!hasRows) return <p>Chưa có vụ nào trong phạm vi này.</p>
  if (focus === 'missing') {
    return (
      <>
        <p><Ico name="check" size={14} /> Không còn vụ nào thiếu thông tin có thể bổ sung.</p>
        {limitedOnly > 0 && <p className="ops-note">{limitedOnly} vụ chỉ vướng giới hạn của bộ hệ số — nhập thêm không giải quyết được. <Link to="/carbon?loc=methodology_limited">Xem ở Carbon</Link></p>}
      </>
    )
  }
  if (focus === 'carbon') return <p>Không có vụ nào ở trạng thái này.</p>
  return <p>Không có vụ nào khớp bộ lọc.</p>
}

function SeasonRow({ r, focus, selected, onOpen }: { r: OpsRow; focus: SeasonsFocus; selected: boolean; onOpen: () => void }) {
  const carbon = CARBON_LABEL[r.carbon]
  const where = `vụ ${r.seasonName}, ${r.plotName ?? 'chưa rõ thửa'}, ${r.farmName}`
  const emphasis = focus === 'missing' && r.missing.length ? ' is-attention'
    : focus === 'carbon' && r.carbon === 'stale' ? ' is-attention'
      : focus === 'carbon' && r.carbon === 'ready' ? ' is-ready' : ''
  const identity = <>
    <td data-label="Nông hộ"><b>{r.farmName}</b>{r.farmCode && <small>{r.farmCode}</small>}</td>
    <td data-label="Thửa"><b>{r.plotName ?? 'Chưa rõ thửa'}</b>{r.plotCode && <small>{r.plotCode}</small>}</td>
    <td data-label="Vụ"><b className="nowrap">{r.seasonName}</b></td>
  </>
  const skel = (w: number) => <Sk w={w} h={20} />
  const open = (text: string) => (
    <td data-label="" className="ops-act">
      <button type="button" className="btn btn--ghost btn--sm" onClick={onOpen} aria-haspopup="dialog" aria-label={`${text} ${where}`}>{text}</button>
    </td>
  )

  if (focus === 'all') {
    return (
      <tr aria-selected={selected} className={emphasis}>
        {identity}
        <td data-label="Giai đoạn"><Badge role={r.status === 'active' ? 'positive' : 'neutral'}>{r.statusLabel}</Badge></td>
        <td data-label="Gieo sạ" className="nowrap">{shortDate(r.plantingDate) ?? <span className="ops-dash">Chưa ghi</span>}</td>
        <td data-label="Thu hoạch" className="nowrap">{shortDate(r.harvestDate) ?? <span className="ops-dash">Chưa ghi</span>}</td>
        <td data-label="Carbon" className="ops-secondary">{r.loading ? skel(80) : <Badge role={carbon.role}>{carbon.text}</Badge>}</td>
        {open('Chi tiết')}
      </tr>
    )
  }
  if (focus === 'missing') {
    return (
      <tr aria-selected={selected} className={emphasis}>
        {identity}
        <td data-label="Cần bổ sung" className="num">{r.loading ? skel(24) : <b>{r.missing.length}</b>}</td>
        <td data-label="Thông tin còn thiếu">
          {r.loading ? skel(160) : r.missing.length
            ? <ul className="ops-gaps">{r.missing.map((m) => <li key={m.code}>{m.label.replace(/^Thiếu\s+/i, '')}</li>)}</ul>
            : <span className="ops-dash">Đã đủ</span>}
        </td>
        <td data-label="Carbon">{r.loading ? skel(80) : <Badge role={carbon.role}>{carbon.text}</Badge>}</td>
        {open(r.missing.length ? 'Xử lý' : 'Chi tiết')}
      </tr>
    )
  }
  return <CarbonRow r={r} where={where} selected={selected} emphasis={emphasis} identity={identity} onOpen={onOpen} />
}

/** What the Carbon state means for this row, in one cell: the thing to fix
 *  while the season is blocked, the result once there is one. A season that
 *  is still missing data used to carry five result columns that could only
 *  ever say "—"; they are gone, and the cell says what is missing instead. */
export function carbonIssue(r: OpsRow): { head: string; sub?: string } {
  const missing = r.missing.map((m) => m.label.replace(/^Thiếu\s+/i, ''))
  const total = r.totalCo2eKg != null ? `${nf.format(r.totalCo2eKg)} kg CO₂e` : null
  const perKg = r.carbonPerKg != null ? `${perKgFmt(r.carbonPerKg, 'kg CO₂e / kg lúa')}` : null
  switch (r.carbon) {
    case 'missing_data':
      return { head: missing.length ? `Thiếu ${missing.length} thông tin` : 'Thiếu dữ liệu', sub: missing.join(', ') || undefined }
    case 'methodology_limited':
      return { head: r.limitations[0]?.label ?? 'Bộ hệ số chưa đủ', sub: 'Nhập thêm dữ liệu không giải quyết được' }
    case 'ready':
      return { head: 'Đủ dữ liệu, chưa tính' }
    case 'stale':
      return { head: 'Dữ liệu đã đổi sau lần tính', sub: total ? `Kết quả cũ: ${total}` : undefined }
    case 'calculated':
      return { head: total ?? 'Đã có kết quả', sub: perKg ?? undefined }
    default:
      return { head: r.error ? 'Chưa đọc được trạng thái' : '—' }
  }
}

const CARBON_ICON: Partial<Record<OpsRow['carbon'], 'warning' | 'info' | 'clock' | 'check'>> = {
  missing_data: 'warning', methodology_limited: 'info', stale: 'clock', calculated: 'check',
}

/**
 * `/carbon` row. Six columns, not nine: identity (Nông hộ · Thửa · Vụ),
 * one Carbon state, one cell for what to fix or what came out, and the
 * actions. Exactly one action is a labelled button; opening the detail
 * panel is a 40px icon button with a full accessible name, so the action
 * cell has a fixed, small width and can never be pushed past the table's
 * edge (Round 4 clipped it at 1363px). Below 1180px the row becomes a card.
 */
function CarbonRow({ r, where, selected, emphasis, identity, onOpen }: {
  r: OpsRow; where: string; selected: boolean; emphasis: string; identity: React.ReactNode; onOpen: () => void
}) {
  const carbon = CARBON_LABEL[r.carbon]
  const action = carbonRowAction(r)
  const issue = carbonIssue(r)
  const urgent = r.carbon === 'ready' || r.carbon === 'stale'
  return (
    <tr aria-selected={selected} className={`ops-crow${emphasis}`} data-carbon-row>
      {identity}
      <td data-label="Trạng thái Carbon" className="ops-crow__state">
        {r.loading ? <Sk w={96} h={22} /> : <Badge role={carbon.role} icon={CARBON_ICON[r.carbon]}>{carbon.text}</Badge>}
      </td>
      <td data-label="Cần xử lý · Kết quả" className="ops-crow__issue">
        {r.loading ? <Sk w={160} h={16} /> : <><b>{issue.head}</b>{issue.sub && <small>{issue.sub}</small>}</>}
      </td>
      <td data-label="" className="ops-act">
        <span className="ops-act__row">
          {action && !r.loading
            ? <Link to={action.to} data-row-action="primary" className={`btn btn--sm${urgent ? '' : ' btn--ghost'}`} aria-label={`${action.label}: ${where}`}>{action.label}</Link>
            : null}
          <button type="button" data-row-action="secondary" className="btn btn--quiet btn--sm ops-more" onClick={onOpen} aria-haspopup="dialog" aria-label={`Chi tiết ${where}`} title="Chi tiết">
            <Ico name="chevron" size={16} />
          </button>
        </span>
      </td>
    </tr>
  )
}

function SeasonDetailPanel({ row, focus, onClose }: { row: OpsRow; focus: SeasonsFocus; onClose: () => void }) {
  const carbon = CARBON_LABEL[row.carbon]
  const action = carbonRowAction(row)
  return (
    <div className="ops-detail">
      <header>
        <div>
          <p className="ops-detail__eyebrow">{row.farmName}{row.farmCode ? ` · ${row.farmCode}` : ''}</p>
          <h2>{row.seasonName}</h2>
          <small>{row.plotName ?? 'Chưa rõ thửa'}{row.plotCode ? ` (${row.plotCode})` : ''} · {row.statusLabel}</small>
        </div>
        <button type="button" className="btn btn--ghost btn--icon" onClick={onClose} aria-label="Đóng chi tiết vụ" data-drawer-close><Ico name="close" size={16} /></button>
      </header>

      {row.loading && <p className="ops-note" aria-live="polite">Đang đọc dữ liệu của vụ này…</p>}

      <section>
        <h3 tabIndex={-1} data-drawer-missing>Dữ liệu còn thiếu</h3>
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
        {row.totalCo2eKg != null && <p className="ops-note">Tổng: {nf.format(row.totalCo2eKg)} kg CO₂e</p>}
        {row.carbonPerKg != null && <p className="ops-note">{perKgFmt(row.carbonPerKg, 'kg CO₂e / kg lúa')}</p>}
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
        {/* One primary: fix the gap on the data-gaps list; on Carbon, the
          * action the Carbon state allows; otherwise open the season. */}
        {focus === 'carbon' && action
          ? <Link to={action.to} className="btn btn--sm">{action.label}</Link>
          : <Link to={`/crop-seasons/${row.seasonId}`} className="btn btn--sm">{focus === 'missing' && row.missing.length ? 'Mở vụ để bổ sung' : 'Mở vụ mùa'}</Link>}
        {focus !== 'carbon' && <Link to={`/crop-seasons/${row.seasonId}/carbon`} className="btn btn--ghost btn--sm">Carbon của vụ</Link>}
        <Link to={`/farms/${row.farmId}`} className="btn btn--ghost btn--sm">Hồ sơ nông hộ</Link>
      </footer>
    </div>
  )
}
