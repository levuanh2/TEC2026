#!/usr/bin/env node
// F7 security headers: one source (stages.json), three uses.
//
//   node ops/security-headers/headers.mjs --check            invariants (CI-safe, no network)
//   node ops/security-headers/headers.mjs --yaml <stage>     the `headers:` block for render.yaml
//   node ops/security-headers/headers.mjs --json <stage>     {name: value} (used by the harness)
//   node ops/security-headers/headers.mjs --verify <stage>   GET the live site, compare (read-only)
//
// Nothing here changes production. The render.yaml PR built from --yaml IS the
// rollout (Blueprint 'tec' auto-syncs render.yaml from main).
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
export const config = JSON.parse(readFileSync(join(here, 'stages.json'), 'utf8'))

/** Directives a browser ignores in Report-Only (and warns about). */
const ENFORCE_ONLY = new Set(['frame-ancestors', 'sandbox'])

function cspString(spec, reportOnly) {
  const names = spec.directives === 'all' ? Object.keys(config.policy).filter((k) => !k.startsWith('$')) : spec.directives
  return names
    .filter((d) => !(reportOnly && ENFORCE_ONLY.has(d)))
    .map((d) => `${d} ${config.policy[d].join(' ')}`)
    .join('; ')
}

/** The exact headers of a stage, as {name: value}. */
export function headersFor(stage) {
  const s = config.stages[String(stage)]
  if (!s) throw new Error(`unknown stage ${stage}`)
  const out = {}
  for (const [name, value] of Object.entries(s.headers)) {
    out[name] = typeof value === 'string' ? value : cspString(value, name.endsWith('-Report-Only'))
  }
  return out
}

export function yamlFor(stage) {
  const h = headersFor(stage)
  const q = (v) => `"${v.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
  const lines = ['    headers:']
  for (const [name, value] of Object.entries(h)) lines.push(`      - path: /*`, `        name: ${name}`, `        value: ${q(value)}`)
  return Object.keys(h).length ? lines.join('\n') : '    # stage 0: no headers block'
}

/** Invariants. Returns a list of problems (empty = fine). */
export function check() {
  const problems = []
  const stages = Object.keys(config.stages).sort()
  let lastAge = 0
  for (const st of stages) {
    if (st === '0') continue
    const h = headersFor(st)
    const hsts = h['Strict-Transport-Security'] ?? ''
    if (/includesubdomains|preload/i.test(hsts)) problems.push(`stage ${st}: HSTS includeSubDomains/preload before the subdomain audit`)
    const age = Number(/max-age=(\d+)/.exec(hsts)?.[1] ?? NaN)
    if (!Number.isFinite(age)) problems.push(`stage ${st}: HSTS without max-age`)
    if (age < lastAge) problems.push(`stage ${st}: HSTS max-age goes down (${age} < ${lastAge})`)
    if (st === '1' && age > 300) problems.push('stage 1: HSTS must start short (<= 300 s)')
    lastAge = age
    if (h['X-Frame-Options'] !== 'DENY') problems.push(`stage ${st}: X-Frame-Options must be DENY`)
    if (!/frame-ancestors 'none'/.test(h['Content-Security-Policy'] ?? '')) problems.push(`stage ${st}: frame-ancestors 'none' must be ENFORCED`)
    if (/frame-ancestors/.test(h['Content-Security-Policy-Report-Only'] ?? '')) problems.push(`stage ${st}: frame-ancestors in Report-Only is ignored`)
    if (h['X-Content-Type-Options'] !== 'nosniff') problems.push(`stage ${st}: nosniff missing`)
    for (const v of [h['Content-Security-Policy'], h['Content-Security-Policy-Report-Only']]) {
      if (v && /'unsafe-inline'|'unsafe-eval'|\*/.test(v)) problems.push(`stage ${st}: CSP allows unsafe-inline/unsafe-eval/wildcard`)
    }
  }
  const connect = config.policy['connect-src'].join(' ')
  for (const o of [config.origins.api, config.origins.supabase]) if (!connect.includes(o)) problems.push(`connect-src misses ${o}`)
  // The allowed inline handler must be exactly the one in index.html.
  const html = readFileSync(join(here, '../../web-dashboard/index.html'), 'utf8')
  const handlers = [...html.matchAll(/\son[a-z]+="([^"]*)"/g)].map((m) => m[1])
  for (const hnd of handlers) {
    const hash = `sha256-${createHash('sha256').update(hnd).digest('base64')}`
    if (!config.policy['script-src'].includes(`'${hash}'`)) problems.push(`index.html inline handler ${JSON.stringify(hnd)} (${hash}) is not allowed by script-src`)
  }
  for (const [, hash] of Object.entries(config.inlineHandlerHashes).filter(([k]) => !k.startsWith('$'))) {
    if (!handlers.some((hnd) => `sha256-${createHash('sha256').update(hnd).digest('base64')}` === hash)) problems.push(`script-src allows ${hash}, which no handler in index.html has (stale hash)`)
  }
  if (/<script(?![^>]*\bsrc=)[^>]*>/i.test(html)) problems.push('index.html has an inline <script>; script-src does not allow it')
  return problems
}

async function verify(stage, url = config.site) {
  const want = headersFor(stage)
  const res = await fetch(url, { redirect: 'manual' })
  const diff = []
  for (const [name, value] of Object.entries(want)) {
    const got = res.headers.get(name)
    if (got !== value) diff.push({ header: name, want: value, got })
  }
  // Headers that later stages add must not be there early (a half-applied stage).
  const all = new Set(Object.values(config.stages).flatMap((s) => Object.keys(s.headers)))
  for (const name of all) if (!(name in want) && name !== 'X-Content-Type-Options' && res.headers.get(name) !== null) diff.push({ header: name, want: null, got: res.headers.get(name) })
  return { url, status: res.status, stage: String(stage), ok: diff.length === 0, diff }
}

const [mode, arg] = process.argv.slice(2)
if (import.meta.url === `file://${process.argv[1]?.replace(/\\/g, '/').replace(/^([A-Za-z]):/, '/$1:')}` || process.argv[1]?.endsWith('headers.mjs')) {
  if (mode === '--check') {
    const p = check()
    for (const x of p) console.error('FAIL', x)
    console.log(p.length ? `${p.length} problem(s)` : 'security headers config: OK')
    process.exit(p.length ? 1 : 0)
  } else if (mode === '--yaml') console.log(yamlFor(arg))
  else if (mode === '--json') console.log(JSON.stringify(headersFor(arg), null, 1))
  else if (mode === '--verify') {
    const r = await verify(arg)
    console.log(JSON.stringify(r, null, 1))
    process.exit(r.ok ? 0 : 1)
  } else if (mode) { console.error(`unknown mode ${mode}`); process.exit(2) }
}
