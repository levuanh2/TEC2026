import path from 'node:path'
import type { Page } from '@playwright/test'

/* axe-core, injected from the local devDependency (no network). Returns the
 * WCAG 2.1 A/AA violations as plain data, so a spec can assert on them and
 * print them. */
export interface AxeViolation { id: string; impact: string | null; help: string; nodes: string[] }

export async function axe(page: Page, include?: string): Promise<AxeViolation[]> {
  await page.addScriptTag({ path: path.resolve('node_modules/axe-core/axe.min.js') })
  return page.evaluate(async (sel) => {
    const w = window as unknown as { axe: { run: (ctx: unknown, opts: unknown) => Promise<{ violations: { id: string; impact: string | null; help: string; nodes: { target: string[] }[] }[] }> } }
    const r = await w.axe.run(sel ? { include: [sel] } : document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } })
    return r.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.slice(0, 6).map((n) => n.target.join(' ')) }))
  }, include ?? null)
}

/** Serious and critical only — the gate for this round. */
export const blocking = (v: AxeViolation[]) => v.filter((x) => x.impact === 'serious' || x.impact === 'critical')
