import { expireSession } from '../api/auth'
import { errorKind, friendlyError, isRetryable } from '../utils/errorPresentation'
import { useEffect, useRef, type ReactNode } from 'react'
import { Link } from '../ui'
import { Ico, type IconName } from './icons'

/* Farmer V2 component kit. Scoped under `.fw` (see farmer.css) so nothing here
 * can restyle Management, which keeps using ../ui. */

export type Tone = 'forest' | 'leaf' | 'water' | 'earth' | 'terracotta' | 'straw' | 'amber' | 'info' | 'sage' | 'carbon'

export const ACTIVITY_ICON: Record<string, { icon: IconName; tone: Tone }> = {
  seeding: { icon: 'seeding', tone: 'leaf' },
  fertilizer: { icon: 'fertilizer', tone: 'earth' },
  irrigation: { icon: 'irrigation', tone: 'water' },
  pesticide: { icon: 'pesticide', tone: 'terracotta' },
  straw_management: { icon: 'straw', tone: 'straw' },
  harvest: { icon: 'harvest', tone: 'amber' },
  fuel: { icon: 'fuel', tone: 'sage' },
}

export function IconTile({ name, tone = 'forest', size = 'md', className = '' }: { name: IconName; tone?: Tone; size?: 'sm' | 'md' | 'lg'; className?: string }) {
  return <span className={`fw-tile fw-tile--${size} tone-${tone} ${className}`} aria-hidden="true"><Ico name={name} /></span>
}

export function ActivityTile({ type, size = 'md' }: { type: string; size?: 'sm' | 'md' | 'lg' }) {
  const a = ACTIVITY_ICON[type] ?? { icon: 'journal' as IconName, tone: 'sage' as Tone }
  return <IconTile name={a.icon} tone={a.tone} size={size} />
}

export function Chip({ tone = 'sage', icon, children, className = '' }: { tone?: Tone; icon?: IconName; children: ReactNode; className?: string }) {
  return <span className={`fw-chip tone-${tone} ${className}`}>{icon && <Ico name={icon} />}{children}</span>
}

export function PageHeader({ eyebrow, icon, title, subtitle, actions }: { eyebrow?: string; icon?: IconName; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="fw-head">
      <div className="fw-head__text">
        {eyebrow && <p className="fw-head__eyebrow">{icon && <Ico name={icon} />}{eyebrow}</p>}
        <h1>{title}</h1>
        {subtitle && <p className="fw-head__sub">{subtitle}</p>}
      </div>
      {actions && <div className="fw-head__actions">{actions}</div>}
    </header>
  )
}

export function Crumbs({ items }: { items: { label: string; to?: string }[] }) {
  return (
    <nav className="fw-crumbs" aria-label="Breadcrumb">
      {items.map((item, i) => (
        <span key={i} className="fw-crumbs__item">
          {i > 0 && <Ico name="chevron" className="fw-crumbs__sep" />}
          {item.to && i < items.length - 1 ? <Link to={item.to}>{item.label}</Link> : <b aria-current="page">{item.label}</b>}
        </span>
      ))}
    </nav>
  )
}

/** A ruled section head: heading, optional inline note, optional action.
 *
 * Deliberately has no icon tile. Every section carrying `icon + heading +
 * description` is the most repeated block in generated UI, and on the old Home
 * it fired five times on one screen. The rule under the head is the divider;
 * the heading carries the section on its own. `icon`/`tone` stay in the type so
 * callers keep compiling, but nothing renders them. */
export function Section({ title, description, action, children, className = '', labelledBy }: {
  title: string; icon?: IconName; tone?: Tone; description?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; labelledBy?: string
}) {
  return (
    <section className={`fw-section ${className}`} aria-labelledby={labelledBy}>
      <div className="fw-section__head">
        <div className="fw-section__title">
          <h2 id={labelledBy}>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function MoreLink({ to, children }: { to: string; children: ReactNode }) {
  return <Link to={to} className="fw-link">{children}<Ico name="arrow" /></Link>
}

export function Refreshing({ show }: { show: boolean }) {
  return <span className={`fw-refreshing${show ? ' is-on' : ''}`} aria-live="polite">{show ? 'Đang cập nhật…' : ''}</span>
}

export function Empty({ icon = 'leaf', title, body, action, tone = 'sage' }: { icon?: IconName; title: string; body?: ReactNode; action?: ReactNode; tone?: Tone }) {
  return (
    <div className="fw-empty">
      <IconTile name={icon} tone={tone} size="lg" />
      <p className="fw-empty__title">{title}</p>
      {body && <p className="fw-empty__body">{body}</p>}
      {action && <div className="fw-empty__action">{action}</div>}
    </div>
  )
}

const NEUTRAL_404 = 'Không tìm thấy dữ liệu hoặc dữ liệu không thuộc phạm vi truy cập.'
/** A farmer never reads the transport's English. Every failure arrives here
 * as one Vietnamese sentence, and the retry button only appears when trying
 * again is something that could actually work. */
export function ErrorPanel({ error, onRetry }: { error: string; onRetry?: () => void }) {
  const kind = errorKind(error)
  const notFound = kind === 'not-found'
  const TITLE: Record<typeof kind, string> = {
    auth: 'Bạn cần đăng nhập lại',
    'not-found': 'Không tìm thấy',
    offline: 'Không có kết nối',
    unavailable: 'Tạm thời chưa dùng được',
    unknown: 'Không tải được dữ liệu',
  }
  return (
    <div className={`fw-error${notFound ? ' is-notfound' : ''}`} role="alert">
      <IconTile name={notFound ? 'search' : 'warning'} tone={notFound ? 'sage' : 'terracotta'} />
      <div>
        <p className="fw-error__title">{TITLE[kind]}</p>
        <p className="fw-error__body">{notFound ? NEUTRAL_404 : friendlyError(error)}</p>
      </div>
      {kind === 'auth' && <button type="button" className="fw-btn fw-btn--primary" onClick={expireSession}>Đăng nhập lại</button>}
      {onRetry && isRetryable(error) && <button type="button" className="fw-btn fw-btn--soft" onClick={onRetry}><Ico name="refresh" />Thử lại</button>}
    </div>
  )
}

/* ------------------------------------------------------------ skeletons */

export function Sk({ w, h = 14, r, className = '' }: { w?: number | string; h?: number | string; r?: number; className?: string }) {
  return <span className={`fw-sk ${className}`} style={{ width: w, height: h, borderRadius: r }} />
}
export function SkBlock({ children, label = 'Đang tải', className = '' }: { children: ReactNode; label?: string; className?: string }) {
  return <div className={`fw-sk-block ${className}`} aria-busy="true" aria-label={label}>{children}</div>
}

/* --------------------------------------------------------------- tabs */

export function Tabs({ items }: { items: { label: string; to: string; icon: IconName; current: boolean }[] }) {
  return (
    <div className="fw-tabs" role="tablist" aria-label="Khu vực của vụ">
      {items.map((t) => (
        <Link key={t.to} to={t.to} className="fw-tab" role="tab" aria-selected={t.current} aria-current={t.current ? 'page' : undefined}>
          <Ico name={t.icon} />{t.label}
        </Link>
      ))}
    </div>
  )
}

export function Flash({ message }: { message: string | null }) {
  if (!message) return null
  return <p className="fw-notice fw-notice--success" role="status"><Ico name="check" />{message}</p>
}

export function Fact({ icon, label, value }: { icon: IconName; label: string; value: ReactNode | null | undefined }) {
  const empty = value == null || value === ''
  return (
    <div className="fw-fact">
      <IconTile name={icon} tone="sage" size="sm" />
      <span><small>{label}</small><b className={empty ? 'is-empty' : undefined}>{empty ? 'Chưa ghi nhận' : value}</b></span>
    </div>
  )
}

export function Stat({ value, label, empty }: { value: ReactNode; label: string; empty?: boolean }) {
  return <div className="fw-stat"><b className={empty ? 'is-empty' : undefined}>{value}</b><small>{label}</small></div>
}

/* ------------------------------------------------------ overlays */

function useEscape(onClose: () => void, disabled?: boolean) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !disabled) onClose() }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [onClose, disabled])
}

function useFocusOnOpen() {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    const node = ref.current
    if (node && !node.contains(document.activeElement)) node.focus()
    const { overflow } = document.body.style
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = overflow; prev?.focus?.() }
  }, [])
  return ref
}

export function FarmerSheet({ title, subtitle, icon, tone = 'forest', onClose, busy, children, wide }: {
  title: string; subtitle?: string; icon?: IconName; tone?: Tone; onClose: () => void; busy?: boolean; children: ReactNode; wide?: boolean
}) {
  useEscape(onClose, busy)
  const ref = useFocusOnOpen()
  return (
    <div className="fw-overlay" onClick={() => !busy && onClose()}>
      <div ref={ref} tabIndex={-1} className={`fw-sheet${wide ? ' fw-sheet--wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="fw-sheet__head">
          {icon && <IconTile name={icon} tone={tone} />}
          <div className="fw-sheet__title">
            <h3>{title}</h3>
            {subtitle && <small>{subtitle}</small>}
          </div>
          <button type="button" className="fw-iconbtn" onClick={onClose} disabled={busy} aria-label="Đóng"><Ico name="close" /></button>
        </div>
        <div className="fw-sheet__body">{children}</div>
      </div>
    </div>
  )
}

export function FarmerConfirm({ title, body, confirmLabel, busy, onConfirm, onCancel, icon = 'delete' }: {
  title: string; body: ReactNode; confirmLabel: string; busy?: boolean; onConfirm: () => void; onCancel: () => void
  /** The mark beside the title; a delete by default. */
  icon?: IconName
}) {
  useEscape(onCancel, busy)
  const ref = useFocusOnOpen()
  return (
    <div className="fw-overlay" onClick={() => !busy && onCancel()}>
      <div ref={ref} tabIndex={-1} className="fw-confirm" role="alertdialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <IconTile name={icon} tone="terracotta" />
        <h3>{title}</h3>
        <div className="fw-confirm__body">{body}</div>
        <div className="fw-confirm__actions">
          <button type="button" className="fw-btn fw-btn--ghost" onClick={onCancel} disabled={busy} autoFocus>Hủy</button>
          <button type="button" className="fw-btn fw-btn--danger" onClick={onConfirm} disabled={busy}>{busy ? 'Đang xử lý…' : confirmLabel}</button>
        </div>
      </div>
    </div>
  )
}

export function FarmerDrawer({ title, subtitle, icon, onClose, children }: { title: string; subtitle?: string; icon?: ReactNode; onClose: () => void; children: ReactNode }) {
  useEscape(onClose)
  const ref = useFocusOnOpen()
  return (
    <div className="fw-overlay fw-overlay--side" onClick={onClose}>
      <div ref={ref} tabIndex={-1} className="fw-drawer" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="fw-sheet__head">
          {icon}
          <div className="fw-sheet__title">
            <h3>{title}</h3>
            {subtitle && <small>{subtitle}</small>}
          </div>
          <button type="button" className="fw-iconbtn" onClick={onClose} aria-label="Đóng"><Ico name="close" /></button>
        </div>
        <div className="fw-sheet__body">{children}</div>
      </div>
    </div>
  )
}
