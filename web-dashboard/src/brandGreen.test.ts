import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

/* Round 4.1 token guard: TDMU institutional green is the navigation's colour
 * and nowhere else. Reads the shipped stylesheets, so a later edit that points
 * a workspace control back at the forest — or uses a sidebar token outside the
 * sidebar — fails here before it reaches a screenshot. */

// Vitest does not load CSS (and `?raw` of a .css comes back empty), so read from disk.
const read = (p: string) => readFileSync(new URL(p, import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
const FILES = { 'theme.css': read('./theme.css'), 'styles.css': read('./styles.css'), 'farmer/tokens.css': read('./farmer/tokens.css'), 'farmer/farmer.css': read('./farmer/farmer.css') }

/** The selector of the rule that contains position `i`. */
function selectorAt(css: string, i: number): string {
  const open = css.lastIndexOf('{', i)
  const start = Math.max(css.lastIndexOf('}', open), css.lastIndexOf('{', open - 1)) + 1
  return css.slice(start, open).trim()
}
function uses(pattern: RegExp) {
  const out: { file: string; selector: string }[] = []
  for (const [file, css] of Object.entries(FILES)) {
    for (const m of css.matchAll(pattern)) out.push({ file, selector: selectorAt(css, m.index!) })
  }
  return out
}
/** Token value as declared in theme.css. */
const token = (name: string) => FILES['theme.css'].match(new RegExp(`${name}:\\s*([^;]+);`))?.[1].trim() ?? ''
const hueOf = (v: string) => { const m = v.match(/oklch\(\s*[\d.]+%?\s+([\d.]+)\s+([\d.]+)/); return m ? { c: +m[1], h: +m[2] } : null }

// `.avatar` is the initials chip in the Management sidebar footer (App.tsx, `.sidebar__foot`).
const NAVIGATION = /(^|[\s,])(:root|\.fw)\s*$|sidebar|\.nav\b|\.brand|\.avatar|fw-side|fw-nav|fw-bottom/

describe('institutional green stays in navigation', () => {
  it('sidebar tokens are only used by navigation rules', () => {
    const offenders = uses(/var\(--(ac-sidebar[\w-]*|fw-navbar[\w-]*)\)/g).filter((u) => !NAVIGATION.test(u.selector))
    expect(offenders).toEqual([])
  })

  it('the forest accent tokens are not used by any rule', () => {
    const offenders = uses(/var\(--ac-accent(-hover|-deep)?\)/g).filter((u) => !/^(:root|\.fw)$/.test(u.selector))
    expect(offenders).toEqual([])
  })

  it('workspace CTA, marker, accent and focus tokens are not green', () => {
    for (const name of ['--ac-cta', '--ac-cta-hover', '--ac-marker', '--ac-work', '--ac-work-strong', '--ac-work-soft', '--ac-focus']) {
      const v = hueOf(token(name))
      expect(v, `${name} is not an oklch() value`).not.toBeNull()
      expect(v!.h >= 120 && v!.h <= 180 && v!.c >= 0.015, `${name} = ${token(name)}`).toBe(false)
    }
  })

  it('both apps map their accent aliases to the workspace tokens', () => {
    const styles = FILES['styles.css'], farmer = FILES['farmer/tokens.css']
    for (const alias of ['--accent', '--brand', '--brand-strong', '--brand-soft']) {
      expect(styles.match(new RegExp(`${alias}:\\s*var\\((--[\\w-]+)\\)`))?.[1], alias).toMatch(/^--ac-(work|cta)/)
    }
    for (const alias of ['--fw-accent', '--fw-accent-deep', '--fw-accent-soft']) {
      expect(farmer.match(new RegExp(`${alias}:\\s*var\\((--[\\w-]+)\\)`))?.[1], alias).toMatch(/^--ac-work/)
    }
  })

  it('semantic "done" green is the #E2F0CB role family, not the forest', () => {
    expect(token('--ac-success')).toBe('var(--ac-role-positive-ink)')
    expect(token('--ac-success-mark')).toBe('var(--ac-role-positive-line)')
    expect(FILES['farmer/tokens.css']).toMatch(/--fw-ok:\s*var\(--ac-success-mark\)/)
  })

  it('the sidebar itself is still the institutional green', () => {
    const v = hueOf(token('--ac-sidebar'))!
    expect(v.h).toBeGreaterThanOrEqual(120)
    expect(v.h).toBeLessThanOrEqual(180)
    expect(v.c).toBeGreaterThan(0.04)
  })
})
