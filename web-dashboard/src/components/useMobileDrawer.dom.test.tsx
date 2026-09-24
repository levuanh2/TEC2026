// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { Sidebar } from './Sidebar'
import { useMobileDrawer } from './useMobileDrawer'

/* Round 4.3 — the Management sidebar as a modal drawer on phones. The harness
 * wires the hook and the real Sidebar exactly as AppShell does. */

let phone = true
const listeners = new Set<() => void>()
function stubMatchMedia() {
  window.matchMedia = ((query: string) => ({
    get matches() { return phone },
    media: query,
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  })) as unknown as typeof window.matchMedia
}

function Shell() {
  const [path, setPath] = useState('/dashboard')
  const drawer = useMobileDrawer(path)
  return (
    <div className="shell">
      {drawer.open && <div className="shell-backdrop" data-testid="drawer-backdrop" aria-hidden="true" onClick={drawer.close} />}
      <Sidebar
        className={drawer.open ? 'is-open' : undefined}
        drawer={{ id: 'app-drawer', open: drawer.open, mobile: drawer.mobile, onClose: drawer.close, asideRef: drawer.drawerRef, closeRef: drawer.closeRef }}
        home="/dashboard" tagline="t" navLabel="Điều hướng chính"
        groups={[{ key: 'a', items: [
          { to: '/dashboard', label: 'Tổng quan', icon: null, current: path === '/dashboard', onClick: drawer.close },
          { to: '/seasons', label: 'Vụ mùa', icon: null, current: path === '/seasons', onClick: drawer.close },
        ] }]}
        foot={<button type="button">Đăng xuất</button>}
      />
      <div className="main" data-testid="main" inert={drawer.open ? true : undefined}>
        <button type="button" aria-label="Mở menu" aria-expanded={drawer.open} aria-controls="app-drawer" ref={drawer.openerRef} onClick={drawer.toggle}>≡</button>
        <button type="button" onClick={() => setPath('/seasons')}>Điều hướng giả lập</button>
      </div>
    </div>
  )
}

const opener = () => screen.getByRole('button', { name: 'Mở menu' })
const aside = () => document.querySelector('aside.sidebar') as HTMLElement
const tab = (shift = false) => fireEvent.keyDown(document, { key: 'Tab', shiftKey: shift })

beforeEach(() => { phone = true; listeners.clear(); stubMatchMedia() })
afterEach(() => { cleanup(); document.body.style.overflow = '' })

describe('Management drawer ≤768px', () => {
  it('closed: the drawer is inert, so its links are out of the tab order', () => {
    render(<Shell />)
    expect(aside().hasAttribute('inert')).toBe(true)
    expect(screen.queryByTestId('drawer-backdrop')).toBeNull()
    expect(opener().getAttribute('aria-expanded')).toBe('false')
  })

  it('open: backdrop, focus on the named close button, inert workspace, no body scroll', () => {
    render(<Shell />)
    fireEvent.click(opener())
    expect(screen.getByTestId('drawer-backdrop')).toBeTruthy()
    const close = screen.getByRole('button', { name: 'Đóng menu' })
    expect(document.activeElement).toBe(close)
    expect(aside().hasAttribute('inert')).toBe(false)
    expect(aside().getAttribute('role')).toBe('dialog')
    expect(aside().getAttribute('aria-modal')).toBe('true')
    expect(screen.getByTestId('main').hasAttribute('inert')).toBe(true)
    expect(document.body.style.overflow).toBe('hidden')
  })

  it('a tap on the backdrop closes it and focus returns to the menu button', () => {
    render(<Shell />)
    fireEvent.click(opener())
    fireEvent.click(screen.getByTestId('drawer-backdrop'))
    expect(screen.queryByTestId('drawer-backdrop')).toBeNull()
    expect(aside().classList.contains('is-open')).toBe(false)
    expect(document.activeElement).toBe(opener())
    expect(document.body.style.overflow).toBe('')
    expect(screen.getByTestId('main').hasAttribute('inert')).toBe(false)
  })

  it('Escape closes it and returns focus', () => {
    render(<Shell />)
    fireEvent.click(opener())
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(aside().classList.contains('is-open')).toBe(false)
    expect(document.activeElement).toBe(opener())
  })

  it('the close button closes it', () => {
    render(<Shell />)
    fireEvent.click(opener())
    fireEvent.click(screen.getByRole('button', { name: 'Đóng menu' }))
    expect(aside().classList.contains('is-open')).toBe(false)
    expect(document.activeElement).toBe(opener())
  })

  it('Tab and Shift+Tab stay inside the drawer', () => {
    render(<Shell />)
    fireEvent.click(opener())
    const items = [...aside().querySelectorAll<HTMLElement>('a[href], button')]
    const first = items[0]
    const last = items[items.length - 1]
    last.focus()
    tab()
    expect(document.activeElement).toBe(first)
    first.focus()
    tab(true)
    expect(document.activeElement).toBe(last)
  })

  it('a route change closes it', () => {
    render(<Shell />)
    fireEvent.click(opener())
    // The workspace is inert while open; the route change arrives from outside
    // (a nav link, history). Simulate it directly.
    act(() => { (screen.getByText('Điều hướng giả lập') as HTMLButtonElement).click() })
    expect(aside().classList.contains('is-open')).toBe(false)
  })

  it('above the breakpoint nothing is modal: no inert, no dialog role, the menu never opens', () => {
    phone = false
    render(<Shell />)
    expect(aside().hasAttribute('inert')).toBe(false)
    fireEvent.click(opener())
    expect(aside().getAttribute('role')).toBeNull()
    expect(screen.queryByTestId('drawer-backdrop')).toBeNull()
    expect(screen.getByTestId('main').hasAttribute('inert')).toBe(false)
  })

  it('growing past the breakpoint while open returns to the rail', () => {
    render(<Shell />)
    fireEvent.click(opener())
    phone = false
    act(() => { for (const fn of listeners) fn() })
    expect(aside().classList.contains('is-open')).toBe(false)
    expect(document.body.style.overflow).toBe('')
  })
})

describe('Farmer sidebar is untouched', () => {
  it('without a drawer config the Sidebar has no close button and is never inert', () => {
    render(<Sidebar home="/farmer" tagline="Nông hộ" navLabel="n" groups={[]} foot={null} />)
    expect(screen.queryByRole('button', { name: 'Đóng menu' })).toBeNull()
    expect(aside().hasAttribute('inert')).toBe(false)
    expect(aside().getAttribute('role')).toBeNull()
  })
})
