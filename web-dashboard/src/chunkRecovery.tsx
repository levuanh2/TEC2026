import { Component, type ErrorInfo, type ReactNode } from 'react'

/* Recovery from a route chunk that cannot be loaded.
 *
 * Since route splitting (routeChunks.ts), every page except the shell is a
 * separate file fetched on first visit. That fetch can fail two ways:
 *  - the network dropped (offline, a flaky mobile link): the same file will
 *    load once the network is back;
 *  - a deployment replaced the files: this tab still runs the previous build
 *    and asks for a hashed file name that no longer exists (404). Retrying the
 *    same name can never work; only the new build can.
 * Without a boundary either one unmounted the whole app (blank page).
 *
 * Policy:
 *  - Always: a neutral message, "Thử lại" (fetch again, no reload) and
 *    "Tải lại trang". Auth, the confirmed role and the query cache are not
 *    touched; the shell around the page stays.
 *  - Automatic reload only with proof that a NEWER BUILD is deployed (the live
 *    index.html names a different entry file than the one running), only once
 *    per new build, and only when no form field on the page holds unsaved
 *    input. Offline, a same-build failure or unsaved input: never automatic.
 */

export const CHUNK_ERROR_TEXT = 'Không tải được nội dung. Vui lòng thử lại.'
const RELOADED_FOR_KEY = 'agricarbon.chunkReloadFor'

const CHUNK_MESSAGE = /dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS|Failed to load module script|ChunkLoadError|Loading chunk [\w-]+ failed/i

/** Errors a failed `import()` of a route chunk produces in Chromium, Firefox
 *  and Safari, plus Vite's own preload failure. */
export function isChunkLoadError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const e = error as { name?: unknown; message?: unknown }
  return e.name === 'ChunkLoadError' || (typeof e.message === 'string' && CHUNK_MESSAGE.test(e.message))
}

let lastPreloadErrorAt = 0
/** Vite dispatches `vite:preloadError` on window when a dependency of a
 *  dynamic import cannot be preloaded, just before that import rejects. The
 *  rejection's own message varies by browser, so a preload error seen moments
 *  earlier also marks the failure as a chunk failure. Nothing is prevented or
 *  reloaded here; the boundary decides. */
export function installPreloadErrorListener(target: Window = window): () => void {
  const on = () => { lastPreloadErrorAt = Date.now() }
  target.addEventListener('vite:preloadError', on)
  return () => target.removeEventListener('vite:preloadError', on)
}
export const recentPreloadError = (withinMs = 10_000): boolean => Date.now() - lastPreloadErrorAt < withinMs
const isChunkFailure = (error: unknown) => isChunkLoadError(error) || recentPreloadError()

/** The entry file this tab is running, e.g. `/assets/index-CanJ1zg6.js`. */
export function runningEntry(doc: Document = document): string | null {
  const s = doc.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/index-"]')
  return s ? new URL(s.src, location.href).pathname : null
}

/** The entry file the server deploys now, read from a fresh index.html. Null
 *  when it cannot be told (offline, an error page, no entry in the HTML). */
export async function deployedEntry(fetchImpl: typeof fetch = fetch): Promise<string | null> {
  try {
    const res = await fetchImpl('/', { cache: 'no-store', headers: { Accept: 'text/html' } })
    if (!res.ok) return null
    const m = (await res.text()).match(/<script[^>]+type="module"[^>]+src="([^"]*\/assets\/index-[^"]+\.js)"/)
    return m ? new URL(m[1], location.href).pathname : null
  } catch {
    return null
  }
}

/* Unsaved input. React keeps a controlled field's `defaultValue` equal to its
 * current value (React 19 syncs the attribute) and never marks the chosen
 * <option> as `defaultSelected`, so comparing a field with its defaults
 * misses typed text and flags untouched selects. What a person typed is
 * therefore recorded from the `input`/`change` events themselves; the
 * default comparison still covers fields changed without React. A field that
 * was edited and is still on the page counts as unsaved even after a save:
 * the safe side (no automatic reload, the reload button asks first). */
const editedFields = new WeakSet<EventTarget>()

/** Record every field a person edits. Installed once at startup (main.tsx). */
export function installEditTracker(target: Document = document): () => void {
  const on = (e: Event) => { if (e.target) editedFields.add(e.target) }
  target.addEventListener('input', on, true)
  target.addEventListener('change', on, true)
  return () => {
    target.removeEventListener('input', on, true)
    target.removeEventListener('change', on, true)
  }
}

/** Any form field still on the page that a person edited, or whose value
 *  differs from what it was rendered with. */
export function hasUnsavedInput(doc: Document = document): boolean {
  for (const el of doc.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('input, textarea, select')) {
    if (el instanceof HTMLInputElement && (el.type === 'hidden' || el.type === 'submit' || el.type === 'button')) continue
    if (editedFields.has(el)) return true
    if (el instanceof HTMLInputElement) {
      if (el.type === 'checkbox' || el.type === 'radio') { if (el.checked !== el.defaultChecked) return true; continue }
      if (el.value !== el.defaultValue) return true
    } else if (el instanceof HTMLTextAreaElement) {
      if (el.value !== el.defaultValue) return true
    } else if ([...el.options].some((o) => o.defaultSelected)) {
      // Only a select with a marked default can be compared (see above).
      if ([...el.options].some((o) => o.selected !== o.defaultSelected)) return true
    }
  }
  return false
}

function readReloadedFor(): string | null {
  try { return sessionStorage.getItem(RELOADED_FOR_KEY) } catch { return null }
}
function writeReloadedFor(entry: string): boolean {
  try { sessionStorage.setItem(RELOADED_FOR_KEY, entry); return sessionStorage.getItem(RELOADED_FOR_KEY) === entry } catch { return false }
}

export type ChunkVerdict = 'reload' | 'new-build-unsaved' | 'new-build-already-reloaded' | 'offline' | 'same-build' | 'unknown'
export type ChunkDecision = { verdict: ChunkVerdict; deployed: string | null }

/** Decide whether this failure justifies the one automatic reload. */
export async function chunkVerdict(deps: {
  online?: boolean
  running?: string | null
  deployed?: () => Promise<string | null>
  unsaved?: () => boolean
  reloadedFor?: () => string | null
} = {}): Promise<ChunkDecision> {
  const online = deps.online ?? navigator.onLine
  if (!online) return { verdict: 'offline', deployed: null }
  const running = deps.running === undefined ? runningEntry() : deps.running
  const deployed = await (deps.deployed ?? deployedEntry)()
  const verdict: ChunkVerdict = !running || !deployed ? 'unknown'
    : deployed === running ? 'same-build'
    : (deps.reloadedFor ?? readReloadedFor)() === deployed ? 'new-build-already-reloaded'
    : (deps.unsaved ?? hasUnsavedInput)() ? 'new-build-unsaved'
    : 'reload'
  return { verdict, deployed }
}

/** Reload into the new build, at most once per deployed entry. The marker is
 *  written BEFORE reloading; if storage is unavailable no automatic reload
 *  happens (it could not be bounded). */
export function reloadOnceFor(deployed: string, reload: () => void = () => location.reload()): boolean {
  if (!writeReloadedFor(deployed)) return false
  reload()
  return true
}

/* ------------------------------------------------------------- boundary */

type Props = {
  children: ReactNode
  /** A change (e.g. the path) clears the error, so navigating elsewhere works. */
  resetKey?: unknown
  /** Called before a retry re-renders the children (drop failed lazy loads). */
  onRetry?: () => void
  /** The boundary replaces a whole screen (no shell around it): frame it. */
  fullPage?: boolean
  /** Injectable for tests. */
  decide?: () => Promise<ChunkDecision>
  autoReload?: (deployed: string) => boolean
  reloadPage?: () => void
  confirmLoss?: (message: string) => boolean
}
type State = { error: unknown; resetKey: unknown; note: string | null }

export class ChunkErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey, note: null }

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error, note: null }
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey !== state.resetKey ? { error: null, resetKey: props.resetKey, note: null } : null
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    const chunk = isChunkFailure(error)
    console.error('route_render_failed', chunk ? 'chunk_load' : 'render', error, info.componentStack)
    if (chunk) void this.maybeReload()
  }

  private async maybeReload() {
    const { verdict, deployed } = await (this.props.decide ?? chunkVerdict)()
    if (verdict === 'reload' && deployed && (this.props.autoReload ?? reloadOnceFor)(deployed)) return
    const note = verdict === 'offline' ? 'Thiết bị đang mất kết nối mạng.'
      : verdict === 'new-build-unsaved' ? 'Hệ thống vừa được cập nhật. Trang có dữ liệu chưa lưu nên không tự tải lại.'
      : verdict === 'new-build-already-reloaded' ? 'Hệ thống vừa được cập nhật nhưng vẫn chưa tải được nội dung.'
      : null
    if (this.state.error) this.setState({ note })
  }

  private retry = () => {
    this.props.onRetry?.()
    this.setState({ error: null, note: null })
  }

  private reload = () => {
    if (hasUnsavedInput() && !(this.props.confirmLoss ?? ((m) => window.confirm(m)))(
      'Trang đang có dữ liệu chưa lưu. Tải lại sẽ mất dữ liệu này. Vẫn tải lại?')) return
    ;(this.props.reloadPage ?? (() => location.reload()))()
  }

  render() {
    if (!this.state.error) return this.props.children
    const chunk = isChunkFailure(this.state.error)
    const body = (
      <div className="state" role="alert" data-testid="chunk-error">
        <p className="state__title">{chunk ? CHUNK_ERROR_TEXT : 'Không hiển thị được nội dung này. Vui lòng thử lại.'}</p>
        {this.state.note && <p className="state__body">{this.state.note}</p>}
        <div className="state__actions">
          <button type="button" className="btn" onClick={this.retry}>Thử lại</button>
          <button type="button" className="btn btn--ghost" onClick={this.reload}>Tải lại trang</button>
        </div>
      </div>
    )
    return this.props.fullPage ? <main className="login"><section className="login-card">{body}</section></main> : body
  }
}
