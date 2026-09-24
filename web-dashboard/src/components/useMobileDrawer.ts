import { useCallback, useEffect, useRef, useState } from 'react'

/* The Management sidebar as a modal drawer on phones (Round 4.3).
 *
 * At ≤768px the sidebar slides over the workspace. It used to do only that:
 * no backdrop, a tap on the page behind did nothing, Escape did nothing,
 * focus stayed on the menu button, Tab walked straight out of the drawer into
 * the page underneath, and the page kept scrolling. This hook owns every one
 * of those behaviours so the shell only wires refs and attributes:
 *
 *   open  → focus moves to the drawer's close button, Tab cycles inside it,
 *           the workspace is `inert`, the body cannot scroll
 *   close → backdrop tap, Escape, the close button, or a route change;
 *           focus returns to the button that opened it
 *
 * Above the breakpoint it does nothing at all: desktop and tablet keep their
 * static rail, and the Farmer shell (bottom navigation) never uses it. */

export const DRAWER_QUERY = '(max-width: 768px)'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function focusables(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.hasAttribute('inert') && el.getAttribute('aria-hidden') !== 'true')
}

function matches(query: string): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches
}

export interface MobileDrawer {
  /** The drawer is open AND the viewport is a phone. */
  open: boolean
  /** The viewport is at or under the breakpoint. */
  mobile: boolean
  toggle: () => void
  close: () => void
  drawerRef: React.RefObject<HTMLElement | null>
  openerRef: React.RefObject<HTMLButtonElement | null>
  closeRef: React.RefObject<HTMLButtonElement | null>
}

export function useMobileDrawer(path: string, query: string = DRAWER_QUERY): MobileDrawer {
  const [requested, setRequested] = useState(false)
  const [mobile, setMobile] = useState(() => matches(query))
  const drawerRef = useRef<HTMLElement | null>(null)
  const openerRef = useRef<HTMLButtonElement | null>(null)
  const closeRef = useRef<HTMLButtonElement | null>(null)
  const open = requested && mobile

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia(query)
    const sync = () => {
      setMobile(mq.matches)
      // Growing past the breakpoint turns the drawer back into the rail.
      if (!mq.matches) setRequested(false)
    }
    sync()
    mq.addEventListener?.('change', sync)
    return () => mq.removeEventListener?.('change', sync)
  }, [query])

  // A navigation always lands on a closed drawer.
  useEffect(() => { setRequested(false) }, [path])

  useEffect(() => {
    if (!open) return
    const drawer = drawerRef.current
    const opener = openerRef.current
    ;(closeRef.current ?? (drawer && focusables(drawer)[0]))?.focus()

    const body = document.body
    const prevOverflow = body.style.overflow
    body.style.overflow = 'hidden'

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        setRequested(false)
        return
      }
      if (e.key !== 'Tab' || !drawer) return
      const items = focusables(drawer)
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      const inside = active instanceof Node && drawer.contains(active)
      if (e.shiftKey && (active === first || !inside)) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && (active === last || !inside)) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      body.style.overflow = prevOverflow
      // Back to where the reader was. Only if focus is not already somewhere
      // meaningful outside the drawer (a link that navigated moved it on).
      const active = document.activeElement
      if (!active || active === document.body || (drawer && drawer.contains(active))) opener?.focus()
    }
  }, [open])

  const toggle = useCallback(() => setRequested((o) => !o), [])
  const close = useCallback(() => setRequested(false), [])
  return { open, mobile, toggle, close, drawerRef, openerRef, closeRef }
}
