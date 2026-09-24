import type { ReactNode } from 'react'
import { Link } from '../ui'

/* One sidebar for both roles (Round 4.2). The Farmer shell drew its own copy
 * — 232px against Management's 240px token, a different brand line, a
 * different row grid, and a row padding that pointed at a spacing token that
 * does not exist — so the two drifted apart one fix at a time. Both shells
 * now render this component and share its styles (styles.css, "Shell"); what
 * each role passes in is only content: the brand line, the destinations and
 * the account block. */

export interface SideItem {
  to: string
  label: string
  icon: ReactNode
  current: boolean
  onClick?: () => void
  onWarm?: () => void
}
/** `label` is omitted for the first group, whose single overview row sits
 *  directly under the brand. `labelHidden` keeps a label visual-only where it
 *  would only repeat the one row beneath it for a screen reader. */
export interface SideGroup { key: string; label?: string; labelHidden?: boolean; items: SideItem[] }

export function Sidebar({ className, home, tagline, navLabel, groups, foot }: {
  className?: string
  home: string
  tagline: string
  navLabel: string
  groups: SideGroup[]
  foot: ReactNode
}) {
  return (
    <aside className={`sidebar${className ? ` ${className}` : ''}`}>
      <Link to={home} className="brand">
        AgriCarbon
        <small>{tagline}</small>
      </Link>
      <nav className="nav" aria-label={navLabel}>
        {groups.map((g) => (
          <div className="nav-group" key={g.key}>
            {g.label && <div className="nav-group__label" aria-hidden={g.labelHidden || undefined}>{g.label}</div>}
            {g.items.map((it) => (
              <Link
                key={it.to}
                to={it.to}
                aria-current={it.current ? 'page' : undefined}
                onClick={it.onClick}
                onMouseEnter={it.onWarm}
                onFocus={it.onWarm}
              >
                <span className="nav__ico">{it.icon}</span>
                {it.label}
              </Link>
            ))}
          </div>
        ))}
      </nav>
      <div className="sidebar__foot">{foot}</div>
    </aside>
  )
}

/** An address may break after its `@` and nowhere else, so a long one reads
 *  as "local@" over "domain" rather than losing its domain to an ellipsis.
 *  Anything still too long for a line is clipped by CSS; the element carries
 *  the full text as `title`, and the text itself stays whole in the DOM. */
export function AccountName({ text }: { text: string }) {
  const at = text.indexOf('@')
  return (
    <b className="sidebar__name" title={text}>
      {at > 0 ? <>{text.slice(0, at + 1)}<wbr />{text.slice(at + 1)}</> : text}
    </b>
  )
}
