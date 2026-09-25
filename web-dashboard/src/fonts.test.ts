import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

/* Round 4.4: Fraunces was removed after no rule referenced it (`--ac-serif`
 * was defined and never used) while index.html still downloaded it on every
 * page. Keep it gone: a display face comes back only as a deliberate
 * decision that also updates this test. */

const read = (p: string) => readFileSync(new URL(p, import.meta.url), 'utf8')
const STYLES = ['./theme.css', './styles.css', './farmer/tokens.css', './farmer/farmer.css']
const SOURCES = import.meta.glob(['./**/*.tsx', '!./**/*.test.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>
const NAMES_FRAUNCES = /font-family[^;]*Fraunces|--[\w-]+:\s*[^;]*Fraunces|fontFamily[^,}]*Fraunces/i

describe('webfont request', () => {
  it('index.html requests Be Vietnam Pro and no Fraunces', () => {
    const html = read('../index.html')
    const hrefs = [...html.matchAll(/href="(https:\/\/fonts\.googleapis\.com\/css2[^"]+)"/g)].map((m) => m[1])
    expect(hrefs.length).toBeGreaterThan(0)
    for (const h of hrefs) {
      expect(h).toContain('family=Be+Vietnam+Pro')
      expect(h).not.toMatch(/Fraunces/i)
    }
  })

  it('no stylesheet or component names Fraunces as a font', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(20)
    const offenders = [
      ...STYLES.filter((f) => NAMES_FRAUNCES.test(read(f))),
      ...Object.entries(SOURCES).filter(([, src]) => NAMES_FRAUNCES.test(src)).map(([f]) => f),
    ]
    expect(offenders).toEqual([])
  })
})
