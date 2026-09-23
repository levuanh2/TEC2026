import { errorKind, friendlyError, isRetryable } from './utils/errorPresentation'
import { Ico, type IconName } from './icons'
import { useCallback, useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react'

/* ---------------------------------------------------------------- routing */

export function go(to: string) {
  if (to === location.pathname + location.search) return
  history.pushState({}, '', to)
  dispatchEvent(new PopStateEvent('popstate'))
}

export function Link({
  to, className, children, onClick, ...rest
}: { to: string; className?: string; children: ReactNode; onClick?: (e: MouseEvent<HTMLAnchorElement>) => void } & Record<string, unknown>) {
  return (
    <a
      href={to}
      className={className}
      onClick={(e) => {
        // A caller-supplied onClick (e.g. closing the mobile sidebar drawer)
        // must run ALONGSIDE the SPA navigation, not replace it — destructuring
        // it out here (rather than leaving it in `rest`, spread last) is what
        // makes that composition happen instead of the caller's handler
        // silently clobbering this one and falling through to a full page
        // reload (real bug: every Management sidebar link did exactly this).
        onClick?.(e)
        if (e.metaKey || e.ctrlKey || e.shiftKey) return
        e.preventDefault()
        go(to)
      }}
      {...rest}
    >
      {children}
    </a>
  )
}

/* ------------------------------------------------------------ data loading */

type AsyncState<T> = { data?: T; error?: string; loading: boolean }

/** One place for the loading/error/data lifecycle so pages don't each re-implement it. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ loading: true })
  const [nonce, setNonce] = useState(0)
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    let alive = true
    setState({ loading: true })
    fnRef.current()
      .then((data) => alive && setState({ data, loading: false }))
      .catch((e) => alive && setState({ error: e instanceof Error ? e.message : 'Không thể tải dữ liệu.', loading: false }))
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { ...state, reload: useCallback(() => setNonce((n) => n + 1), []) }
}

/* ------------------------------------------------------------- page frame */

export function Breadcrumb({ items }: { items: { label: string; to?: string }[] }) {
  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      {items.map((item, i) => (
        <span key={i} style={{ display: 'contents' }}>
          {i > 0 && <span className="breadcrumb__sep" aria-hidden="true">/</span>}
          {item.to && i < items.length - 1 ? <Link to={item.to}>{item.label}</Link> : <b aria-current="page">{item.label}</b>}
        </span>
      ))}
    </nav>
  )
}

export function PageHead({
  eyebrow,
  title,
  meta,
  actions,
}: {
  eyebrow?: string
  title: ReactNode
  meta?: ReactNode[]
  actions?: ReactNode
}) {
  return (
    <header className="page-head">
      <div>
        {eyebrow && <p className="page-head__eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {meta && meta.length > 0 && (
          <div className="page-head__meta">
            {meta.map((m, i) => (
              <span key={i}>{m}</span>
            ))}
          </div>
        )}
      </div>
      {actions && <div className="page-head__actions">{actions}</div>}
    </header>
  )
}

/**
 * Identity banner for a page's primary subject (organization, farm, active
 * season) — one shared component instead of each page hand-rolling its own
 * gradient header markup (brief: "reuse components instead of writing
 * page-specific duplicated CSS").
 */
export function Hero({
  eyebrow,
  title,
  titleAs = 'h2',
  meta,
  stats,
  actions,
}: {
  eyebrow?: string
  title: ReactNode
  /** Use 'h1' when Hero is the page's only title (no separate PageHead above
   * it) so the page keeps exactly one real <h1> for a11y/tests. Defaults to
   * 'h2' for pages where a route-level PageHead already provides the h1. */
  titleAs?: 'h1' | 'h2'
  meta?: ReactNode[]
  stats?: { label: string; value: ReactNode }[]
  actions?: ReactNode
}) {
  const Title = titleAs
  return (
    <div className="hero">
      <div className="hero__id">
        {eyebrow && <span className="hero__eyebrow">{eyebrow}</span>}
        <Title className="hero__title">{title}</Title>
        {meta && meta.length > 0 && (
          <div className="hero__meta">
            {meta.map((m, i) => (
              <span key={i}>{m}</span>
            ))}
          </div>
        )}
      </div>
      {stats && stats.length > 0 && (
        <div className="hero__stats">
          {stats.map((s, i) => (
            <div className="hero__stat" key={i}>
              <b>{s.value}</b>
              <span>{s.label}</span>
            </div>
          ))}
        </div>
      )}
      {actions && <div className="hero__actions">{actions}</div>}
    </div>
  )
}

/** Shared table chrome (wrap/scroll/empty) so pages stop re-declaring the
 * same .table-wrap + <table class="data"> boilerplate per page. */
/** A navigable row is a real link, not a `<tr>` with a click handler.
 *
 * `rowHref` turns the FIRST cell into an anchor that is stretched over the
 * whole row by CSS, so the row keeps its large click target while the thing
 * being activated is an `<a>`: it takes tab focus, Enter follows it, the
 * browser offers open-in-new-tab, and a screen reader announces a link with
 * the row's key as its name. Nothing is clickable that cannot be reached
 * from the keyboard. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  rowHref,
  rowLabel,
}: {
  columns: { label: string; align?: 'num'; render: (row: T) => ReactNode; headClassName?: string }[]
  rows: T[]
  rowKey: (row: T) => string
  rowHref?: (row: T) => string
  /** Accessible name for the row link, when the first cell alone is too terse. */
  rowLabel?: (row: T) => string
}) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th key={i} className={[c.align === 'num' ? 'num' : '', c.headClassName ?? ''].filter(Boolean).join(' ')}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className={rowHref ? 'has-rowlink' : undefined}>
              {/* The label travels with each cell so a phone can render the
                * row as a card instead of scrolling the table sideways. */}
              {columns.map((c, i) => (
                <td key={i} data-label={c.label} className={c.align === 'num' ? 'num' : undefined}>
                  {rowHref && i === 0
                    ? <Link to={rowHref(row)} className="rowlink" aria-label={rowLabel?.(row)}>{c.render(row)}</Link>
                    : c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Section({
  title,
  description,
  cta,
  children,
}: {
  title: string
  description?: string
  cta?: { label: string; to: string }
  children: ReactNode
}) {
  return (
    <section className="section">
      <div className="section__head">
        <div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {cta && (
          <Link to={cta.to} className="section__cta">
            {cta.label} <Ico name="arrow" size={14} />
          </Link>
        )}
      </div>
      {children}
    </section>
  )
}

export function Tabs({ items }: { items: { label: string; to: string; current: boolean }[] }) {
  return (
    <div className="tabs" role="tablist">
      {items.map((t) => (
        <Link key={t.to} to={t.to} className="tab" role="tab" aria-current={t.current ? 'page' : undefined}>
          {t.label}
        </Link>
      ))}
    </div>
  )
}

/* --------------------------------------------------------------- metrics */

const isEmptyValue = (v: ReactNode) => typeof v === 'string' && (v === 'Chưa đủ dữ liệu' || v === '—')

export function Kpi({
  label,
  value,
  sub,
  accent,
  variant,
}: {
  label: string
  value: ReactNode
  sub?: string
  accent?: boolean
  variant?: 'sub'
}) {
  return (
    <article className={`kpi${accent ? ' kpi--accent' : ''}${variant === 'sub' ? ' kpi--sub' : ''}`}>
      <span className="kpi__label">{label}</span>
      <span className={`kpi__value${isEmptyValue(value) ? ' is-empty' : ''}`}>{value}</span>
      {sub && <span className="kpi__sub">{sub}</span>}
    </article>
  )
}

export function MetricCard({
  name,
  value,
  unit,
  context,
  status,
}: {
  name: string
  value: ReactNode
  unit?: string
  context?: string
  status?: { tone: Tone; label: string }
}) {
  return (
    <article className="metric-card">
      <div className="metric-card__top">
        <span className="metric-card__name">{name}</span>
        {status && <Badge tone={status.tone}>{status.label}</Badge>}
      </div>
      <div className={`metric-card__value${isEmptyValue(value) ? ' is-empty' : ''}`}>
        {value}
        {unit && !isEmptyValue(value) && <small>{unit}</small>}
      </div>
      {context && <span className="metric-card__ctx">{context}</span>}
    </article>
  )
}

/* ---------------------------------------------------------------- badges */

export type Tone = 'success' | 'warning' | 'error' | 'info' | 'neutral'

export function Badge({ tone = 'neutral', dot, children }: { tone?: Tone; dot?: boolean; children: ReactNode }) {
  return (
    <span className={`badge badge--${tone}`}>
      {dot && <span className="badge__dot" aria-hidden="true" />}
      {children}
    </span>
  )
}

const DATA_STATUS: Record<string, { tone: Tone; label: string }> = {
  complete: { tone: 'success', label: 'Đầy đủ dữ liệu' },
  partial: { tone: 'warning', label: 'Thiếu một phần' },
  missing: { tone: 'error', label: 'Chưa có dữ liệu' },
}
export function DataStatusBadge({ status }: { status: string }) {
  const s = DATA_STATUS[status] ?? { tone: 'neutral' as Tone, label: status }
  return <Badge tone={s.tone} dot>{s.label}</Badge>
}

/* ---------------------------------------------------------- misc widgets */

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Progress({ value, max, unitLabel }: { value: number; max: number; unitLabel: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div>
      <div className="progress-head">
        <b>
          {value}/{max}
        </b>
        <span>{unitLabel}</span>
      </div>
      <div className="progress" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
        <div className="progress__fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export function DL({ items }: { items: { term: string; value: ReactNode }[] }) {
  return (
    <dl className="dl">
      {items.map((it, i) => (
        <div key={i}>
          <dt>{it.term}</dt>
          <dd>{it.value}</dd>
        </div>
      ))}
    </dl>
  )
}

/* ------------------------------------------------------ L / E / Empty states */

export function LoadingSkeleton({ variant = 'page' }: { variant?: 'page' | 'kpis' | 'table' }) {
  if (variant === 'kpis')
    return (
      <div className="kpi-strip" aria-busy="true" aria-label="Đang tải">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="skeleton sk-kpi" />
        ))}
      </div>
    )
  if (variant === 'table')
    return (
      <div className="card card--pad" aria-busy="true" aria-label="Đang tải">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="skeleton sk-row" />
        ))}
      </div>
    )
  return (
    <div aria-busy="true" aria-label="Đang tải">
      <div className="skeleton sk-line" style={{ width: '38%', height: 24 }} />
      <div className="kpi-strip" style={{ marginTop: 20 }}>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="skeleton sk-kpi" />
        ))}
      </div>
      <div className="card card--pad" style={{ marginTop: 24 }}>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="skeleton sk-row" />
        ))}
      </div>
    </div>
  )
}

export function EmptyState({ title, body, icon = 'task', action }: { title: string; body?: string; icon?: IconName; action?: ReactNode }) {
  return (
    <div className="state">
      <div className="state__icon">
        <Ico name={icon} size={18} />
      </div>
      <p className="state__title">{title}</p>
      {body && <p className="state__body">{body}</p>}
      {action && <div className="state__actions">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry, kind = 'error' }: { error: string; onRetry?: () => void; kind?: 'error' | 'warning' }) {
  // Never the transport's own words: "Thiếu header Authorization." told the
  // reader nothing they could act on and read as a crash.
  const failure = errorKind(error)
  const notFound = failure === 'not-found'
  const denied = failure === 'auth'
  const TITLE: Record<ReturnType<typeof errorKind>, string> = {
    auth: 'Phiên đăng nhập đã hết hạn',
    'not-found': 'Không tìm thấy',
    offline: 'Mất kết nối máy chủ',
    unavailable: 'Tạm thời chưa dùng được',
    unknown: 'Không tải được dữ liệu',
  }
  return (
    <div className={`state state--${kind}`}>
      <div className="state__icon">
        <Ico name={notFound ? 'search' : denied ? 'denied' : 'warning'} size={18} />
      </div>
      <p className="state__title">{TITLE[failure]}</p>
      <p className="state__body">{friendlyError(error)}</p>
      {onRetry && isRetryable(error) && (
        <div className="state__actions">
          <button className="btn btn--ghost" onClick={onRetry}>
            Thử lại
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * Render one of loading / error / empty / content from a useAsync() result so
 * every page handles these states identically (brief §18).
 */
export function Async<T>({
  state,
  skeleton = 'page',
  isEmpty,
  empty,
  children,
}: {
  state: AsyncState<T> & { reload: () => void }
  skeleton?: 'page' | 'kpis' | 'table'
  isEmpty?: (data: T) => boolean
  empty?: ReactNode
  children: (data: T) => ReactNode
}) {
  if (state.loading) return <LoadingSkeleton variant={skeleton} />
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />
  if (state.data === undefined) return <ErrorState error="Không có dữ liệu." />
  if (isEmpty && isEmpty(state.data)) return <>{empty ?? <EmptyState title="Chưa có dữ liệu" />}</>
  return <>{children(state.data)}</>
}

/* --------------------------------------------------------------- drawer */

export function Drawer({ title, subtitle, onClose, children }: { title: string; subtitle?: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="drawer__head">
          <div>
            <h3>{title}</h3>
            {subtitle && <small>{subtitle}</small>}
          </div>
          <button className="drawer__close" onClick={onClose} aria-label="Đóng">
            <Ico name="close" size={16} />
          </button>
        </div>
        <div className="drawer__body">{children}</div>
      </div>
    </div>
  )
}

export function Notice({ children, kind = 'info' }: { children: ReactNode; kind?: 'info' | 'warning' | 'error' | 'success' }) {
  return <p className={`notice ${kind}`}>{children}</p>
}

/* ----------------------------------------------------------------- sheet */

/**
 * Focused form surface: centered modal on desktop, full-screen sheet on
 * mobile (brief FW-2 §4/§30). Distinct from Drawer (read-only detail panel).
 */
export function Sheet({ title, subtitle, onClose, busy, children }: { title: string; subtitle?: string; onClose: () => void; busy?: boolean; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !busy && onClose()
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [onClose, busy])
  return (
    <div className="sheet-overlay" onClick={() => !busy && onClose()}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="sheet__head">
          <div>
            <h3>{title}</h3>
            {subtitle && <small>{subtitle}</small>}
          </div>
          <button className="sheet__close" onClick={onClose} disabled={busy} aria-label="Đóng">
            <Ico name="close" size={16} />
          </button>
        </div>
        <div className="sheet__body">{children}</div>
      </div>
    </div>
  )
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  tone = 'default',
  busy,
  onConfirm,
  onCancel,
}: {
  title: string
  body: ReactNode
  confirmLabel: string
  tone?: 'default' | 'danger'
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !busy && onCancel()
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [onCancel, busy])
  return (
    <div className="sheet-overlay" onClick={() => !busy && onCancel()}>
      <div className="confirm-dialog" role="alertdialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        <p>{body}</p>
        <div className="confirm-dialog__actions">
          <button className="btn btn--ghost" onClick={onCancel} disabled={busy} autoFocus>
            Hủy
          </button>
          <button className={tone === 'danger' ? 'btn btn--danger' : 'btn'} onClick={onConfirm} disabled={busy}>
            {busy ? 'Đang xử lý…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ side drawer */

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * A detail panel that slides over the page instead of taking a column from it.
 *
 * The old split layout gave the drawer ~380px of the table's width, so every
 * season code wrapped onto three lines and badges were cut. This overlays:
 * the table behind keeps its layout exactly. It is a modal dialog — focus is
 * trapped inside, Esc and the backdrop close it, and focus goes back to the
 * control that opened it. Under 900px it becomes a full-screen sheet.
 */
export function SideDrawer({ label, onClose, children, initialFocus }: {
  label: string
  onClose: () => void
  children: ReactNode
  /** Selector inside the drawer to focus first; defaults to the close button. */
  initialFocus?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const panel = ref.current
    const first = (initialFocus && panel?.querySelector<HTMLElement>(initialFocus)) || panel?.querySelector<HTMLElement>('[data-drawer-close]')
    first?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); closeRef.current(); return }
      if (e.key !== 'Tab' || !panel) return
      const items = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement)
      if (!items.length) return
      const head = items[0]
      const tail = items[items.length - 1]
      if (e.shiftKey && (document.activeElement === head || !panel.contains(document.activeElement))) { e.preventDefault(); tail.focus() }
      else if (!e.shiftKey && document.activeElement === tail) { e.preventDefault(); head.focus() }
    }
    document.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
      // Back to the row that opened it, if that row is still on the page.
      if (opener && document.contains(opener)) opener.focus()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return (
    <div className="drawer-layer">
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <div className="side-drawer" role="dialog" aria-modal="true" aria-label={label} ref={ref}>
        {children}
      </div>
    </div>
  )
}
