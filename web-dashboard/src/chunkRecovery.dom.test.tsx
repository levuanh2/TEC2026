// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Suspense, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CHUNK_ERROR_TEXT, ChunkErrorBoundary, chunkVerdict, deployedEntry, hasUnsavedInput, installEditTracker, isChunkLoadError,
  reloadOnceFor, runningEntry, type ChunkDecision,
} from './chunkRecovery'
import { lazyRoute, retryFailedChunks } from './routeChunks'

/* A route chunk that cannot be fetched must never blank the app: the boundary
 * shows a neutral retry, reloads by itself only into a NEWER deployed build,
 * at most once per build and never over unsaved input. */

const chunk404 = () => new TypeError('Failed to fetch dynamically imported module: https://agricarbon.info.vn/assets/mrv-OLD123.js')
const offline = () => new TypeError('error loading dynamically imported module')

/** A route whose loader the test controls; counts load attempts. */
function controlledRoute() {
  const ctl = { attempts: 0, fail: null as null | (() => Error) }
  const Page = lazyRoute(async () => {
    ctl.attempts++
    if (ctl.fail) throw ctl.fail()
    return { Page: () => <p>page-content</p> }
  }, 'Page')
  return { ctl, Page }
}
const decision = (verdict: ChunkDecision['verdict'], deployed: string | null = '/assets/index-NEW.js') =>
  () => Promise.resolve({ verdict, deployed })

beforeEach(() => { try { sessionStorage.clear() } catch { /* */ } vi.spyOn(console, 'error').mockImplementation(() => {}) })
afterEach(() => { cleanup(); vi.restoreAllMocks(); document.body.innerHTML = ''; document.head.querySelectorAll('script').forEach((s) => s.remove()) })

describe('classification helpers', () => {
  it('recognises the chunk errors of Chromium, Firefox, Safari and Vite preload; not other errors', () => {
    for (const m of ['Failed to fetch dynamically imported module: x.js', 'error loading dynamically imported module',
      'Importing a module script failed.', 'Unable to preload CSS for /assets/x.css', 'Failed to load module script'])
      expect(isChunkLoadError(new TypeError(m))).toBe(true)
    expect(isChunkLoadError({ name: 'ChunkLoadError', message: '' })).toBe(true)
    expect(isChunkLoadError(new TypeError("Cannot read properties of undefined (reading 'x')"))).toBe(false)
    expect(isChunkLoadError(null)).toBe(false)
  })

  it('reads the running entry from the document and the deployed entry from a fresh index.html', async () => {
    const s = document.createElement('script'); s.type = 'module'; s.src = '/assets/index-OLD.js'; document.head.appendChild(s)
    expect(runningEntry()).toBe('/assets/index-OLD.js')
    const html = '<script type="module" crossorigin src="/assets/index-NEW.js"></script>'
    const f = vi.fn(async () => new Response(html, { status: 200 }))
    expect(await deployedEntry(f as unknown as typeof fetch)).toBe('/assets/index-NEW.js')
    expect(f).toHaveBeenCalledWith('/', expect.objectContaining({ cache: 'no-store' }))
    expect(await deployedEntry((async () => { throw new TypeError('offline') }) as unknown as typeof fetch)).toBeNull()
    expect(await deployedEntry((async () => new Response('down', { status: 503 })) as unknown as typeof fetch)).toBeNull()
  })

  it('detects unsaved input (text, textarea, checkbox, select) and ignores untouched fields', () => {
    document.body.innerHTML = '<input id="a" value="x"><textarea id="t">y</textarea><input id="c" type="checkbox"><select id="s"><option>1</option><option>2</option></select>'
    expect(hasUnsavedInput()).toBe(false)
    ;(document.getElementById('a') as HTMLInputElement).value = 'changed'
    expect(hasUnsavedInput()).toBe(true)
    ;(document.getElementById('a') as HTMLInputElement).value = 'x'
    ;(document.getElementById('c') as HTMLInputElement).checked = true
    expect(hasUnsavedInput()).toBe(true)
    ;(document.getElementById('c') as HTMLInputElement).checked = false
    expect(hasUnsavedInput()).toBe(false)
    const stop = installEditTracker()
    try {
      // A select without a marked default is judged by the person's change event.
      const s = document.getElementById('s') as HTMLSelectElement
      s.selectedIndex = 1
      fireEvent.change(s)
      expect(hasUnsavedInput()).toBe(true)
    } finally { stop() }
  })

  it('React controlled fields: typed text counts as unsaved, an untouched controlled select does not', () => {
    // React 19 keeps defaultValue equal to value on controlled fields, and marks
    // no option defaultSelected, so only the edit events tell what was typed.
    function Form() {
      const [text, setText] = useState('')
      const [note, setNote] = useState('')
      const [unit, setUnit] = useState('kg')
      return (
        <form>
          <input aria-label="text" value={text} onChange={(e) => setText(e.target.value)} />
          <textarea aria-label="note" value={note} onChange={(e) => setNote(e.target.value)} />
          <select aria-label="unit" value={unit} onChange={(e) => setUnit(e.target.value)}>
            <option value="t">t</option><option value="kg">kg</option>
          </select>
        </form>
      )
    }
    const stop = installEditTracker()
    try {
      render(<Form />)
      expect(hasUnsavedInput()).toBe(false)
      fireEvent.change(screen.getByLabelText('text'), { target: { value: 'ghi chú' } })
      expect((screen.getByLabelText('text') as HTMLInputElement).defaultValue).toBe('ghi chú')
      expect(hasUnsavedInput()).toBe(true)
      cleanup()
      render(<Form />)
      expect(hasUnsavedInput()).toBe(false)
      fireEvent.change(screen.getByLabelText('note'), { target: { value: 'chưa lưu' } })
      expect(hasUnsavedInput()).toBe(true)
    } finally { stop() }
  })
})

describe('the one automatic reload', () => {
  const base = { online: true, running: '/assets/index-OLD.js', deployed: async () => '/assets/index-NEW.js', unsaved: () => false, reloadedFor: () => null }

  it('only for a newer deployed build; never offline, same build, unknown, or with unsaved input', async () => {
    expect((await chunkVerdict(base)).verdict).toBe('reload')
    expect((await chunkVerdict({ ...base, online: false })).verdict).toBe('offline')
    expect((await chunkVerdict({ ...base, deployed: async () => '/assets/index-OLD.js' })).verdict).toBe('same-build')
    expect((await chunkVerdict({ ...base, deployed: async () => null })).verdict).toBe('unknown')
    expect((await chunkVerdict({ ...base, running: null })).verdict).toBe('unknown')
    expect((await chunkVerdict({ ...base, unsaved: () => true })).verdict).toBe('new-build-unsaved')
  })

  it('no reload loop: after reloading into a build, the same build never reloads again', async () => {
    const reload = vi.fn()
    expect(reloadOnceFor('/assets/index-NEW.js', reload)).toBe(true)
    expect(reload).toHaveBeenCalledTimes(1)
    // The page came back on the new build but the chunk still fails (e.g. CDN lag):
    const again = await chunkVerdict({ ...base, reloadedFor: undefined })
    expect(again.verdict).toBe('new-build-already-reloaded')
    // A later, different build may reload once more.
    expect((await chunkVerdict({ ...base, reloadedFor: undefined, deployed: async () => '/assets/index-NEWER.js' })).verdict).toBe('reload')
  })

  it('no reload when storage cannot record the marker (it could not be bounded)', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    const reload = vi.fn()
    expect(reloadOnceFor('/assets/index-NEW.js', reload)).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })
})

describe('ChunkErrorBoundary with a real lazy route', () => {
  function mount(Page: React.ComponentType, props: Partial<React.ComponentProps<typeof ChunkErrorBoundary>> = {}) {
    return render(
      <ChunkErrorBoundary onRetry={retryFailedChunks} decide={decision('same-build')} {...props}>
        <Suspense fallback={<p>loading</p>}><Page /></Suspense>
      </ChunkErrorBoundary>,
    )
  }

  it('404 chunk: neutral message with Thử lại and Tải lại trang, nothing blank', async () => {
    const { ctl, Page } = controlledRoute(); ctl.fail = chunk404
    mount(Page)
    const box = await screen.findByTestId('chunk-error')
    expect(box.textContent).toContain(CHUNK_ERROR_TEXT)
    expect(screen.getByRole('button', { name: 'Thử lại' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Tải lại trang' })).toBeTruthy()
  })

  it('network failure, then the network is back: Thử lại loads the page without a reload', async () => {
    const { ctl, Page } = controlledRoute(); ctl.fail = offline
    const autoReload = vi.fn(() => true)
    mount(Page, { decide: decision('offline', null), autoReload })
    await screen.findByTestId('chunk-error')
    expect(await screen.findByText('Thiết bị đang mất kết nối mạng.')).toBeTruthy()
    ctl.fail = null
    fireEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('page-content')).toBeTruthy()
    expect(ctl.attempts).toBe(2)
    expect(autoReload).not.toHaveBeenCalled()
  })

  it('still failing on retry: the message comes back (no loop of retries by itself)', async () => {
    const { ctl, Page } = controlledRoute(); ctl.fail = chunk404
    mount(Page)
    await screen.findByTestId('chunk-error')
    fireEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    await screen.findByTestId('chunk-error')
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(ctl.attempts).toBe(2)
  })

  it('newer build deployed and no unsaved input: reloads by itself, once', async () => {
    const { ctl, Page } = controlledRoute(); ctl.fail = chunk404
    const autoReload = vi.fn(() => true)
    mount(Page, { decide: decision('reload'), autoReload })
    await waitFor(() => expect(autoReload).toHaveBeenCalledWith('/assets/index-NEW.js'))
    expect(autoReload).toHaveBeenCalledTimes(1)
  })

  it('newer build but unsaved input: no automatic reload; Tải lại trang asks first and respects "no"', async () => {
    document.body.insertAdjacentHTML('afterbegin', '<input id="draft" value="">')
    ;(document.getElementById('draft') as HTMLInputElement).value = 'ghi chú chưa lưu'
    const { ctl, Page } = controlledRoute(); ctl.fail = chunk404
    const autoReload = vi.fn(() => true)
    const reloadPage = vi.fn()
    const confirmLoss = vi.fn(() => false)
    mount(Page, {
      decide: () => chunkVerdict({ online: true, running: '/assets/index-OLD.js', deployed: async () => '/assets/index-NEW.js', reloadedFor: () => null }),
      autoReload, reloadPage, confirmLoss,
    })
    expect(await screen.findByText(/dữ liệu chưa lưu nên không tự tải lại/)).toBeTruthy()
    expect(autoReload).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Tải lại trang' }))
    expect(confirmLoss).toHaveBeenCalled()
    expect(reloadPage).not.toHaveBeenCalled()
    expect((document.getElementById('draft') as HTMLInputElement).value).toBe('ghi chú chưa lưu')
    confirmLoss.mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: 'Tải lại trang' }))
    expect(reloadPage).toHaveBeenCalledTimes(1)
  })

  it('a non-chunk render error gets the generic message and never an automatic reload', async () => {
    const Boom = () => { throw new TypeError("Cannot read properties of undefined (reading 'x')") }
    const decide = vi.fn(decision('reload'))
    render(<ChunkErrorBoundary decide={decide}><Boom /></ChunkErrorBoundary>)
    expect((await screen.findByTestId('chunk-error')).textContent).toContain('Không hiển thị được nội dung này')
    expect(decide).not.toHaveBeenCalled()
  })

  it('a new resetKey (navigating elsewhere) clears the error', async () => {
    const { ctl, Page } = controlledRoute(); ctl.fail = chunk404
    const Other = () => <p>other-page</p>
    const view = (key: string, Child: React.ComponentType) => (
      <ChunkErrorBoundary resetKey={key} onRetry={retryFailedChunks} decide={decision('same-build')}>
        <Suspense fallback={<p>loading</p>}><Child /></Suspense>
      </ChunkErrorBoundary>
    )
    const r = render(view('/mrv', Page))
    await screen.findByTestId('chunk-error')
    r.rerender(view('/dashboard', Other))
    expect(await screen.findByText('other-page')).toBeTruthy()
  })
})
