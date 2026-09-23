import type { Page } from '@playwright/test'

/* Round 4.1 helpers shared by the mock and real gates. */

/** True for the TDMU institutional green family: a dark colour at hue
 *  120–180. `minChroma` is 0.015 for fills and rules — Round 4's CTA was a
 *  near-black green at chroma 0.022 and still read as green across a whole
 *  button — and 0.04 for text, where a faint tint in near-black ink does not.
 *  Reads the computed colour as Chrome reports it (oklch() for tokens, rgb()
 *  for hex roles). */
export function isInstitutionalGreen(css: string, minChroma = 0.015): boolean {
  const ok = css.match(/oklch\(\s*([\d.]+%?)\s+([\d.]+)\s+([\d.]+)/)
  if (ok) {
    const l = ok[1].endsWith('%') ? parseFloat(ok[1]) / 100 : parseFloat(ok[1])
    const c = parseFloat(ok[2]); const h = parseFloat(ok[3])
    return c >= minChroma && h >= 120 && h <= 180 && l < 0.6
  }
  const rgb = css.match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/)
  if (!rgb) return false
  const [r, g, b] = rgb.slice(1, 4).map((v) => parseFloat(v) / 255)
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min
  if (d < 0.08 || max !== g) return false
  const hue = 60 * (((b - r) / d) + 2)
  return hue >= 100 && hue <= 175 && (max + min) / 2 < 0.45
}

export interface ActionBox {
  name: string; kind: string; left: number; right: number; w: number; h: number
  containerLeft: number; limitRight: number; inside: boolean; hit: boolean
}

/** Every row action on a Management list, measured at rest: nothing scrolled
 *  sideways, only the window moved vertically to bring each control into
 *  view. `inside` = wholly within min(container right, viewport) and right of
 *  the container's left edge, with a non-empty box; `hit` = the control is
 *  the topmost element at its own centre (visible and clickable). */
export function measureRowActions(page: Page): Promise<{ viewport: number; wrapOverflow: number; docOverflow: number; boxes: ActionBox[] }> {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth
    const wrap = document.querySelector('.ops-table__wrap') as HTMLElement | null
    document.querySelectorAll<HTMLElement>('*').forEach((n) => { if (n.scrollLeft) n.scrollLeft = 0 })
    const controls = [...document.querySelectorAll<HTMLElement>('[data-row-action]')]
    const boxes = controls.map((el) => {
      const y = el.getBoundingClientRect().top + window.scrollY - innerHeight / 2
      window.scrollTo(0, Math.max(0, y))
      const r = el.getBoundingClientRect()
      const wr = wrap?.getBoundingClientRect()
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
      const limitRight = Math.min(wr ? wr.right : vw, vw)
      const containerLeft = wr ? wr.left : 0
      return {
        name: el.getAttribute('aria-label') ?? el.textContent!.trim(), kind: el.dataset.rowAction!,
        left: r.left, right: r.right, w: r.width, h: r.height, containerLeft, limitRight,
        inside: r.right <= limitRight + 0.5 && r.left >= containerLeft - 0.5 && r.width > 0 && r.height > 0,
        hit: Boolean(top && (top === el || el.contains(top))),
      }
    })
    window.scrollTo(0, 0)
    return {
      viewport: vw,
      wrapOverflow: wrap ? wrap.scrollWidth - wrap.clientWidth : 0,
      docOverflow: document.documentElement.scrollWidth - vw,
      boxes,
    }
  })
}
