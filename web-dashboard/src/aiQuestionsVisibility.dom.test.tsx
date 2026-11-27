// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from './query/client'
import { aiQuestionsVisible, useAiQuestionsVisible } from './features/aiQuestionsVisibility'

/* V-1b: the season Q&A panel is shown only when the build flag is on AND /v1/me said
 * `ai_qa_available: true` for the CURRENT verified session. /v1/me is mapped by the REAL
 * toCurrentUser (only its network answer is faked); both shells render a probe that reads the
 * same hook the season pages use. Visibility is not authorization (backend tests cover that). */

type Raw = Record<string, unknown>
let raw: () => Promise<Raw>
const signIn = vi.fn()
const mounts = { farmer: 0, ops: 0 }
let ended: ((reason: 'expired' | 'signed_out') => void) | null = null
let session: { access_token: string; user: { id: string; email: string; app_metadata: object } } | null

vi.mock('./api/auth', () => ({
  onSignOutOutcome: () => () => {},
  canConfirmSignOut: () => false,
  confirmSignOut: async () => false,
  onAuthEnded: (fn: typeof ended) => { ended = fn; return () => { ended = null } },
  onSessionRefreshed: () => () => {},
  onSessionReplaced: () => () => {},
  restoreSession: async () => session,
  signIn: (...a: unknown[]) => signIn(...a),
  signOut: vi.fn(),
  mustChangePassword: () => false,
}))
vi.mock('./api/me', async (orig) => {
  const real = await orig<typeof import('./api/me')>()
  return { ...real, getMe: async () => real.toCurrentUser(await raw() as never) }
})
vi.mock('./api/organizations', async (orig) => ({ ...(await orig<object>()), getOrganization: async (id: string) => ({ id, name: 'HTX QA' }), clearOrganizationCache: () => {} }))
vi.mock('./farmer/scope', async (orig) => ({ ...(await orig<object>()), prefetchFarmerScope: () => {} }))
vi.mock('./query/prefetch', () => ({ prefetchRouteData: () => {} }))
vi.mock('./api/farms', async (orig) => ({ ...(await orig<object>()), usingMockData: false }))

function Probe({ shell }: { shell: 'farmer' | 'ops' }) {
  const visible = useAiQuestionsVisible()
  useEffect(() => { mounts[shell]++ }, [shell])
  return <p data-testid="probe">{shell}:{visible ? 'qa-visible' : 'qa-hidden'}</p>
}
vi.mock('./farmer/FarmerExperience', () => ({ FarmerExperience: () => <Probe shell="farmer" /> }))
vi.mock('./pages/operations', () => ({
  OperationsOverview: () => <Probe shell="ops" />,
  SeasonsWorkspace: () => <p>seasons-workspace</p>,
}))

const { default: App, REVALIDATE_MIN_INTERVAL_MS } = await import('./App')
const realMe = await vi.importActual<typeof import('./api/me')>('./api/me')

const sessionFor = (id: string) => ({ access_token: `t-${id}`, user: { id, email: `${id}@example.test`, app_metadata: {} } })
const farmerMe = (id: string, extra: Raw = {}): Raw => ({ user_id: id, full_name: 'F', roles: ['farmer'], organization_memberships: [{ organization_id: 'org-1', role: 'farmer' }], farm_memberships: [{ farm_id: 'farm-1', farm_role: 'owner' }], ...extra })
const managerMe = (id: string, extra: Raw = {}): Raw => ({ user_id: id, full_name: 'M', roles: ['cooperative_manager'], organization_memberships: [{ organization_id: 'org-1', role: 'cooperative_manager' }], farm_memberships: [], ...extra })

let now = 1_000_000
const later = () => { now += REVALIDATE_MIN_INTERVAL_MS + 1 }
const focus = () => act(() => { window.dispatchEvent(new Event('focus')) })
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })
const probe = () => screen.queryByTestId('probe')?.textContent ?? null
// A role change swaps shells; the first lazy load of the other shell can exceed waitFor's 1 s on a cold run.
const SHELL_SWITCH = { timeout: 5000 }

beforeEach(() => {
  now = 1_000_000
  vi.spyOn(Date, 'now').mockImplementation(() => now)
  vi.stubEnv('VITE_AI_QA_ENABLED', 'true')
  queryClient.clear(); mounts.farmer = 0; mounts.ops = 0
  localStorage.clear(); signIn.mockReset(); session = sessionFor('qa-1')
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllEnvs() })

async function start(path: string, first: Raw | (() => Promise<Raw>)) {
  raw = typeof first === 'function' ? first : async () => first
  history.replaceState({}, '', path)
  render(<App />)
}

describe('the one rule: build flag AND capability === true', () => {
  it.each([
    [true, true, true], [true, false, false], [true, undefined, false], [true, null, false],
    [true, 'true', false], [true, 1, false], [false, true, false], [false, false, false], [false, undefined, false],
  ])('build %s + capability %s -> %s', (build, capability, expected) => {
    expect(aiQuestionsVisible(build as boolean, capability)).toBe(expected)
  })

  it('outside the App provider the hook is false even with the build flag on', () => {
    function Bare() { return <p>{useAiQuestionsVisible() ? 'shown' : 'hidden'}</p> }
    render(<Bare />)
    expect(screen.getByText('hidden')).toBeTruthy()
  })
})

describe('/v1/me mapping (real toCurrentUser) and the routing hint', () => {
  it.each([[true, true], [false, false], [undefined, false], [null, false], ['true', false], [1, false]])(
    'ai_qa_available %s -> aiQaAvailable %s', (value, expected) => {
      const viewer = realMe.toCurrentUser(farmerMe('qa-1', value === undefined ? {} : { ai_qa_available: value }) as never)
      expect(viewer.aiQaAvailable === true).toBe(expected)
      if (!expected) expect('aiQaAvailable' in viewer).toBe(false)
    })

  it('the capability is never written to, nor restored from, the stored hint', () => {
    const viewer = realMe.toCurrentUser(farmerMe('qa-1', { ai_qa_available: true }) as never)
    realMe.writeViewerHint('qa-1', viewer)
    expect(localStorage.getItem('agricarbon.viewer.v1')).not.toContain('aiQaAvailable')
    localStorage.setItem('agricarbon.viewer.v1', JSON.stringify({ userId: 'qa-1', role: 'farmer', organizationId: 'org-1', aiQaAvailable: true }))
    expect(realMe.readViewerHint('qa-1')).not.toHaveProperty('aiQaAvailable')
  })
})

describe('who sees the panel', () => {
  it.each([
    ['QA farmer', '/farmer', farmerMe('qa-1', { ai_qa_available: true }), 'farmer:qa-visible'],
    ['QA manager', '/dashboard', managerMe('qa-1', { ai_qa_available: true }), 'ops:qa-visible'],
    ['farmer outside the cohort', '/farmer', farmerMe('qa-1', { ai_qa_available: false }), 'farmer:qa-hidden'],
    ['manager outside the cohort', '/dashboard', managerMe('qa-1', { ai_qa_available: false }), 'ops:qa-hidden'],
    ['old backend without the field (farmer)', '/farmer', farmerMe('qa-1'), 'farmer:qa-hidden'],
    ['old backend without the field (manager)', '/dashboard', managerMe('qa-1'), 'ops:qa-hidden'],
    ['null field', '/farmer', farmerMe('qa-1', { ai_qa_available: null }), 'farmer:qa-hidden'],
  ])('%s', async (_name, path, me, expected) => {
    await start(path, me)
    await waitFor(() => expect(probe()).toBe(expected))
  })

  it('build flag off: a QA account sees nothing', async () => {
    vi.stubEnv('VITE_AI_QA_ENABLED', 'false')
    await start('/farmer', farmerMe('qa-1', { ai_qa_available: true }))
    await waitFor(() => expect(probe()).toBe('farmer:qa-hidden'))
  })

  it('while /v1/me is loading no business tree (and so no panel) renders: no flash', async () => {
    let release: (r: Raw) => void = () => {}
    await start('/farmer', () => new Promise<Raw>((r) => { release = r }))
    await settle()
    expect(screen.getByTestId('viewer-verifying')).toBeTruthy()
    expect(probe()).toBeNull()
    release(farmerMe('qa-1', { ai_qa_available: true }))
    await waitFor(() => expect(probe()).toBe('farmer:qa-visible'))
    expect(mounts.farmer).toBe(1)
  })

  it('/v1/me fails: the neutral retry screen, never a panel', async () => {
    await start('/farmer', async () => { throw new Error('network down') })
    expect(await screen.findByTestId('viewer-unverified')).toBeTruthy()
    expect(probe()).toBeNull()
  })
})

describe('session and cache isolation', () => {
  it('capability lost on a re-check (removed from the cohort): caches dropped, tree remounts hidden', async () => {
    await start('/farmer', farmerMe('qa-1', { ai_qa_available: true }))
    await waitFor(() => expect(probe()).toBe('farmer:qa-visible'))
    queryClient.setQueryData(['probe-rows'], ['cached'])
    raw = async () => farmerMe('qa-1', { ai_qa_available: false })
    later(); await focus(); await settle()
    await waitFor(() => expect(probe()).toBe('farmer:qa-hidden'))
    expect(mounts.farmer).toBe(2)
    expect(queryClient.getQueryData(['probe-rows'])).toBeUndefined()
  })

  it('capability gained on a re-check: shown after the remount', async () => {
    await start('/dashboard', managerMe('qa-1', { ai_qa_available: false }))
    await waitFor(() => expect(probe()).toBe('ops:qa-hidden'))
    raw = async () => managerMe('qa-1', { ai_qa_available: true })
    later(); await focus(); await settle()
    await waitFor(() => expect(probe()).toBe('ops:qa-visible'))
  })

  it('a re-check that fails with 401/403 (token revoked): neutral screen, no panel', async () => {
    const { ApiError } = await import('./api/client')
    await start('/farmer', farmerMe('qa-1', { ai_qa_available: true }))
    await waitFor(() => expect(probe()).toBe('farmer:qa-visible'))
    raw = async () => { throw new ApiError(401, 'unauthenticated', 'revoked') }
    later(); await focus(); await settle()
    expect(await screen.findByTestId('viewer-unverified')).toBeTruthy()
    expect(probe()).toBeNull()
  })

  it('farmer QA -> the same account becomes a manager outside the cohort: hidden, no reuse', async () => {
    await start('/farmer', farmerMe('qa-1', { ai_qa_available: true }))
    await waitFor(() => expect(probe()).toBe('farmer:qa-visible'))
    raw = async () => managerMe('qa-1', { ai_qa_available: false })
    later(); await focus(); await settle()
    await waitFor(() => expect(probe()).toBe('ops:qa-hidden'), SHELL_SWITCH)
  })

  it('manager QA -> becomes a farmer outside the cohort: hidden', async () => {
    await start('/dashboard', managerMe('qa-1', { ai_qa_available: true }))
    await waitFor(() => expect(probe()).toBe('ops:qa-visible'))
    raw = async () => farmerMe('qa-1', { ai_qa_available: false })
    later(); await focus(); await settle()
    await waitFor(() => expect(probe()).toBe('farmer:qa-hidden'), SHELL_SWITCH)
  })

  it('QA signs out, an account outside the cohort signs in in the same tab: hidden', async () => {
    await start('/farmer', farmerMe('qa-1', { ai_qa_available: true }))
    await waitFor(() => expect(probe()).toBe('farmer:qa-visible'))
    act(() => ended!('signed_out'))
    await waitFor(() => expect(location.pathname).toBe('/login'))
    expect(probe()).toBeNull()
    const other = sessionFor('outsider-1')
    signIn.mockResolvedValue(other)
    raw = async () => farmerMe('outsider-1', { ai_qa_available: false })
    const form = (await screen.findByRole('button', { name: 'Đăng nhập' })).closest('form')!
    fireEvent.change(form.querySelector('input[name=email]')!, { target: { value: 'outsider-1@example.test' } })
    fireEvent.change(form.querySelector('input[name=password]')!, { target: { value: 'pw' } })
    fireEvent.submit(form)
    await waitFor(() => expect(probe()).toBe('farmer:qa-hidden'))
    expect(localStorage.getItem('agricarbon.viewer.v1') ?? '').not.toContain('aiQaAvailable')
  })

  it('an outsider signs out, a QA account signs in: shown only after ITS /v1/me', async () => {
    session = sessionFor('outsider-1')
    await start('/farmer', farmerMe('outsider-1', { ai_qa_available: false }))
    await waitFor(() => expect(probe()).toBe('farmer:qa-hidden'))
    act(() => ended!('signed_out'))
    await waitFor(() => expect(location.pathname).toBe('/login'))
    let release: (r: Raw) => void = () => {}
    signIn.mockResolvedValue(sessionFor('qa-1'))
    raw = () => new Promise<Raw>((r) => { release = r })
    const form = (await screen.findByRole('button', { name: 'Đăng nhập' })).closest('form')!
    fireEvent.change(form.querySelector('input[name=email]')!, { target: { value: 'qa-1@example.test' } })
    fireEvent.change(form.querySelector('input[name=password]')!, { target: { value: 'pw' } })
    fireEvent.submit(form)
    await settle()
    expect(probe()).toBeNull()
    release(farmerMe('qa-1', { ai_qa_available: true }))
    await waitFor(() => expect(probe()).toBe('farmer:qa-visible'))
  })
})

describe('every entry point of the panel uses the shared rule', () => {
  // Same source scan as fonts.test.ts: every non-test module under src, as raw text.
  const SOURCES = import.meta.glob(['./**/*.{ts,tsx}', '!./**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

  it('each file that renders <SeasonQuestionPanel gates it with useAiQuestionsVisible()', () => {
    const users = Object.entries(SOURCES)
      .filter(([path, text]) => path !== './features/aiQuestions.tsx' && text.includes('<SeasonQuestionPanel'))
    expect(users.map(([path]) => path).sort()).toEqual(['./farmer/pages/Season.tsx', './pages/season.tsx'])
    for (const [path, text] of users) {
      expect(text, path).toContain('useAiQuestionsVisible()')
      for (const line of text.split(/\r?\n/).filter((l) => l.includes('<SeasonQuestionPanel'))) {
        expect(line, path).toMatch(/showQuestions && <SeasonQuestionPanel/)
      }
    }
  })

  it('no module reads the build flag alone to show the panel', () => {
    const readers = Object.entries(SOURCES).filter(([, text]) => /env\.VITE_AI_QA_ENABLED\b/.test(text)).map(([path]) => path)
    expect(readers).toEqual(['./features/aiQuestionsVisibility.ts'])
  })
})
