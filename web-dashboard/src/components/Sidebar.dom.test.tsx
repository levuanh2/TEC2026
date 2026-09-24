// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it } from 'vitest'
import { AccountName, Sidebar } from './Sidebar'

/* Round 4.2: both roles render this sidebar, so what it guarantees is what
 * both get — the current row, the address and the width token. */

afterEach(cleanup)

const groups = [
  { key: 'a', items: [{ to: '/x', label: 'Tổng quan', icon: <svg />, current: true }] },
  { key: 'b', label: 'Canh tác', labelHidden: true, items: [{ to: '/y', label: 'Nhật ký', icon: <svg />, current: false }] },
]

describe('Sidebar', () => {
  it('marks exactly one current row and keeps a visual-only group label out of the accessibility tree', () => {
    render(<Sidebar home="/x" tagline="Nông hộ" navLabel="Điều hướng nông hộ" groups={groups} foot={<span>foot</span>} />)
    const nav = screen.getByRole('navigation', { name: 'Điều hướng nông hộ' })
    expect(nav.querySelectorAll('[aria-current="page"]')).toHaveLength(1)
    expect(screen.getByRole('link', { name: 'Tổng quan' }).getAttribute('aria-current')).toBe('page')
    expect(screen.getByText('Canh tác').getAttribute('aria-hidden')).toBe('true')
    expect(screen.getByRole('link', { name: /AgriCarbon/ }).querySelector('small')!.textContent).toBe('Nông hộ')
  })

  it('an address breaks after "@" only, and keeps its whole text and title', () => {
    render(<AccountName text="qa-farmer-fw1@agricarbon-demo.local" />)
    const b = screen.getByTitle('qa-farmer-fw1@agricarbon-demo.local')
    expect(b.textContent).toBe('qa-farmer-fw1@agricarbon-demo.local')
    expect(b.querySelectorAll('wbr')).toHaveLength(1)
    expect(b.firstChild!.textContent).toBe('qa-farmer-fw1@')
  })

  it('a name without "@" is left whole', () => {
    render(<AccountName text="Nguyễn Văn An" />)
    expect(screen.getByTitle('Nguyễn Văn An').querySelector('wbr')).toBeNull()
  })
})

describe('one width token for both shells', () => {
  const strip = (p: string) => readFileSync(new URL(p, import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
  it('the Farmer grid reads --sidebar-w and declares no sidebar width of its own', () => {
    const farmer = strip('../farmer/farmer.css')
    expect(farmer).toMatch(/\.fw-shell\s*\{[^}]*grid-template-columns:\s*var\(--sidebar-w\)/)
    expect(farmer).not.toMatch(/\.fw-shell\s*\{[^}]*grid-template-columns:\s*\d+px/)
    expect(farmer).not.toMatch(/fw-side|fw-nav__|fw-brand|fw-profile/)
  })
  it('the Management grid reads the same token', () => {
    expect(strip('../styles.css')).toMatch(/\.shell\s*\{[^}]*grid-template-columns:\s*var\(--sidebar-w\)/)
  })
})
