import { useId, useState, type FormEvent, type ReactNode } from 'react'
import {
  createFarmForFarmer, createPlot, listFarmerAccounts, provisionFarmer, provisioningErrorMessage,
  type FarmerAccount, type FarmerStage, type FarmInput, type PlotInput, type ProvisionedFarmer,
} from '../api/farmers'
import { Ico } from '../icons'
import type { Role } from '../types'
import { Async, Badge, Breadcrumb, DataTable, EmptyState, Notice, PageHead, Section, Sheet, go, useAsync, type Tone } from '../ui'

/* Management "Tài khoản nông hộ".
 *
 * Product rule: there is no public farmer sign-up. The cooperative provisions
 * each farmer account and records the official farm/plot structure; the
 * farmer (or the manager) then starts a season. Everything here goes through
 * FastAPI, which reaches the Supabase Auth Admin API server-side. */

export const FARMERS_PATH = '/accounts/farmers'
export const NEW_FARMER_PATH = '/accounts/farmers/new'

const canManage = (role: Role | undefined) => role === 'cooperative_manager'

const STAGE: Record<FarmerStage, { label: string; tone: Tone }> = {
  no_farm: { label: 'Chưa có nông hộ', tone: 'warning' },
  no_plot: { label: 'Chưa có thửa ruộng', tone: 'warning' },
  no_season: { label: 'Sẵn sàng bắt đầu vụ', tone: 'info' },
  history_only: { label: 'Không có vụ đang canh tác', tone: 'neutral' },
  active_season: { label: 'Đang canh tác', tone: 'success' },
}
const STATUS: Record<FarmerAccount['accountStatus'], { label: string; tone: Tone }> = {
  active: { label: 'Đang hoạt động', tone: 'success' },
  locked: { label: 'Đã khoá', tone: 'error' },
  ended: { label: 'Đã rời HTX', tone: 'neutral' },
}

/* ------------------------------------------------------------ list page */

export function FarmerAccountsPage({ organizationId, role }: { organizationId: string | null; role?: Role }) {
  const state = useAsync(() => (organizationId ? listFarmerAccounts(organizationId) : Promise.resolve([])), [organizationId])
  const [sheet, setSheet] = useState<{ kind: 'farm' | 'plot'; farmer: FarmerAccount } | null>(null)
  const manager = canManage(role)
  return (
    <>
      <PageHead
        eyebrow="Quản lý"
        title="Tài khoản nông hộ"
        meta={[<>Nông hộ được HTX cấp tài khoản — không có đăng ký công khai</>]}
        actions={manager ? <button className="btn btn--primary" onClick={() => go(NEW_FARMER_PATH)}><Ico name="plus" size={14} /> Thêm nông hộ</button> : undefined}
      />
      <Async
        state={state}
        isEmpty={(rows) => rows.length === 0}
        empty={<EmptyState icon="users" title="Chưa có tài khoản nông hộ nào"
          body="Thêm nông hộ để cấp tài khoản đăng nhập và gán nông hộ, thửa ruộng cho họ."
          action={manager ? <button className="btn btn--primary" onClick={() => go(NEW_FARMER_PATH)}><Ico name="plus" size={14} /> Thêm nông hộ</button> : undefined} />}
      >
        {(rows) => (
          <DataTable
            rows={rows}
            rowKey={(f) => f.userId}
            columns={[
              { label: 'Nông hộ', render: (f) => <span className="acct-name"><b>{f.fullName ?? '—'}</b><small>{f.email ?? ''}</small></span> },
              { label: 'Tài khoản', render: (f) => <Badge tone={STATUS[f.accountStatus].tone} dot>{STATUS[f.accountStatus].label}</Badge> },
              { label: 'Hộ', render: (f) => f.farms.length ? f.farms.map((x) => x.name).join(', ') : <span className="cell-empty">—</span> },
              { label: 'Thửa', align: 'num', render: (f) => f.plotCount },
              { label: 'Vụ', render: (f) => <Badge tone={STAGE[f.stage].tone}>{f.stage === 'active_season' && f.activeSeasonCount > 1 ? `${f.activeSeasonCount} vụ đang canh tác` : STAGE[f.stage].label}</Badge> },
              { label: '', render: (f) => <RowAction farmer={f} manager={manager} onSheet={(kind) => setSheet({ kind, farmer: f })} /> },
            ]}
          />
        )}
      </Async>
      {sheet && organizationId && (
        <Sheet
          title={sheet.kind === 'farm' ? 'Tạo nông hộ' : 'Gán thửa ruộng'}
          subtitle={sheet.farmer.fullName ?? sheet.farmer.email ?? undefined}
          onClose={() => setSheet(null)}
        >
          {sheet.kind === 'farm'
            ? <FarmOnlyForm onCancel={() => setSheet(null)} submit={(farm) => createFarmForFarmer(organizationId, sheet.farmer.userId, farm)}
                onDone={() => { setSheet(null); state.reload() }} />
            : <PlotOnlyForm onCancel={() => setSheet(null)} submit={(plot) => createPlot(sheet.farmer.primaryFarmId!, plot)}
                onDone={() => { setSheet(null); state.reload() }} />}
        </Sheet>
      )}
    </>
  )
}

/** One next step per row, the one the farmer's stage calls for -- never a
 * row of buttons, and nothing for a viewer who may not act. */
function RowAction({ farmer, manager, onSheet }: { farmer: FarmerAccount; manager: boolean; onSheet: (kind: 'farm' | 'plot') => void }) {
  const view = farmer.primaryFarmId
    ? <button className="btn btn--ghost btn--sm" onClick={() => go(`/farms/${farmer.primaryFarmId}`)}>Xem</button>
    : null
  if (!manager || farmer.accountStatus !== 'active') return view
  switch (farmer.stage) {
    case 'no_farm': return <button className="btn btn--ghost btn--sm" onClick={() => onSheet('farm')}>Tạo nông hộ</button>
    case 'no_plot': return <button className="btn btn--ghost btn--sm" onClick={() => onSheet('plot')}>Gán thửa</button>
    case 'no_season':
    case 'history_only':
      return farmer.idlePlotId ? <button className="btn btn--ghost btn--sm" onClick={() => go(`/plots/${farmer.idlePlotId}`)}>Tạo vụ</button> : view
    default: return view
  }
}

/* ------------------------------------------------------------ form parts */

function Field({ label, required, optional, error, children, id }: { label: string; required?: boolean; optional?: boolean; error?: string; children: ReactNode; id: string }) {
  return (
    <div className="form-field" aria-invalid={error ? 'true' : undefined}>
      <label htmlFor={id}>{label}{required && <span className="form-field__required" aria-hidden="true"> *</span>}{optional && <span className="form-field__opt">Không bắt buộc</span>}</label>
      {children}
      {error && <span className="form-field__error" role="alert">{error}</span>}
    </div>
  )
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
/** "1,25" and "1.25" are the same number here; blank stays blank. */
export const parseArea = (v: string): number | null => {
  const n = Number(v.trim().replace(',', '.'))
  return v.trim() && Number.isFinite(n) ? n : null
}

function useFarmFields(prefix: string) {
  const [v, set] = useState({ farmName: '', farmCode: '', commune: '', district: '', province: '' })
  const ids = { name: useId(), code: useId(), commune: useId(), district: useId(), province: useId() }
  const errors = (): Record<string, string> => ({
    ...(v.farmName.trim() ? {} : { [`${prefix}farmName`]: 'Nhập tên nông hộ.' }),
    ...(v.farmCode.trim() ? {} : { [`${prefix}farmCode`]: 'Nhập mã hộ.' }),
  })
  const render = (err: Record<string, string>) => (
    <>
      <div className="acct-grid">
        <Field id={ids.name} label="Tên nông hộ" required error={err[`${prefix}farmName`]}><input id={ids.name} value={v.farmName} onChange={(e) => set({ ...v, farmName: e.target.value })} placeholder="Ví dụ: Hộ Nguyễn Văn Bình" /></Field>
        <Field id={ids.code} label="Mã hộ" required error={err[`${prefix}farmCode`]}><input id={ids.code} value={v.farmCode} onChange={(e) => set({ ...v, farmCode: e.target.value })} placeholder="Ví dụ: HH-012" /></Field>
      </div>
      <div className="acct-grid acct-grid--3">
        <Field id={ids.commune} label="Xã" optional><input id={ids.commune} value={v.commune} onChange={(e) => set({ ...v, commune: e.target.value })} /></Field>
        <Field id={ids.district} label="Huyện" optional><input id={ids.district} value={v.district} onChange={(e) => set({ ...v, district: e.target.value })} /></Field>
        <Field id={ids.province} label="Tỉnh" optional><input id={ids.province} value={v.province} onChange={(e) => set({ ...v, province: e.target.value })} /></Field>
      </div>
    </>
  )
  return { value: v as FarmInput, errors, render }
}

function usePlotFields(prefix: string) {
  const [v, set] = useState({ name: '', plotCode: '', area: '' })
  const ids = { name: useId(), code: useId(), area: useId() }
  const errors = (): Record<string, string> => {
    const out: Record<string, string> = {}
    if (!v.name.trim()) out[`${prefix}plotName`] = 'Nhập tên thửa.'
    if (!v.plotCode.trim()) out[`${prefix}plotCode`] = 'Nhập mã thửa.'
    const a = parseArea(v.area)
    if (a == null || a <= 0) out[`${prefix}area`] = 'Nhập diện tích lớn hơn 0 (ha).'
    return out
  }
  const render = (err: Record<string, string>) => (
    <div className="acct-grid acct-grid--3">
      <Field id={ids.name} label="Tên thửa" required error={err[`${prefix}plotName`]}><input id={ids.name} value={v.name} onChange={(e) => set({ ...v, name: e.target.value })} placeholder="Ví dụ: Thửa bờ kênh" /></Field>
      <Field id={ids.code} label="Mã thửa" required error={err[`${prefix}plotCode`]}><input id={ids.code} value={v.plotCode} onChange={(e) => set({ ...v, plotCode: e.target.value })} placeholder="Ví dụ: T-01" /></Field>
      <Field id={ids.area} label="Diện tích (ha)" required error={err[`${prefix}area`]}><input id={ids.area} inputMode="decimal" value={v.area} onChange={(e) => set({ ...v, area: e.target.value })} placeholder="Ví dụ: 1,25" /></Field>
    </div>
  )
  const value = (): PlotInput => ({ name: v.name, plotCode: v.plotCode, areaHa: parseArea(v.area) ?? 0 })
  return { value, errors, render }
}

function SheetForm({ onCancel, submitLabel, run, children }: { onCancel: () => void; submitLabel: string; run: () => Promise<void> | null; children: ReactNode }) {
  const [pending, setPending] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (pending) return
    const job = run()
    if (!job) return
    setPending(true); setFailure(null)
    try { await job } catch (err) { setFailure(provisioningErrorMessage(err)); setPending(false) }
  }
  return (
    <form className="acct-form" onSubmit={onSubmit} noValidate>
      {children}
      {failure && <div className="form-error" role="alert">{failure}</div>}
      <div className="acct-form__actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={pending}>Hủy</button>
        <button type="submit" className="btn btn--primary" disabled={pending}>{pending ? 'Đang lưu…' : submitLabel}</button>
      </div>
    </form>
  )
}

function FarmOnlyForm({ onCancel, submit, onDone }: { onCancel: () => void; submit: (f: FarmInput) => Promise<unknown>; onDone: () => void }) {
  const farm = useFarmFields('')
  const [err, setErr] = useState<Record<string, string>>({})
  return (
    <SheetForm onCancel={onCancel} submitLabel="Tạo nông hộ" run={() => {
      const e = farm.errors(); setErr(e)
      return Object.keys(e).length ? null : submit(farm.value).then(onDone)
    }}>
      <p className="muted">Tài khoản này sẽ là chủ hộ (owner) của nông hộ mới.</p>
      {farm.render(err)}
    </SheetForm>
  )
}

function PlotOnlyForm({ onCancel, submit, onDone }: { onCancel: () => void; submit: (p: PlotInput) => Promise<unknown>; onDone: () => void }) {
  const plot = usePlotFields('')
  const [err, setErr] = useState<Record<string, string>>({})
  return (
    <SheetForm onCancel={onCancel} submitLabel="Gán thửa" run={() => {
      const e = plot.errors(); setErr(e)
      return Object.keys(e).length ? null : submit(plot.value()).then(onDone)
    }}>
      {plot.render(err)}
    </SheetForm>
  )
}

/* ------------------------------------------------------- "Thêm nông hộ" */

const STEPS = ['Tài khoản', 'Nông hộ', 'Thửa ruộng', 'Sẵn sàng bắt đầu vụ']

function Steps({ current }: { current: number }) {
  return (
    <ol className="acct-steps" aria-label="Các bước cấp tài khoản nông hộ">
      {STEPS.map((s, i) => (
        <li key={s} className={i < current ? 'is-done' : i === current ? 'is-current' : undefined} aria-current={i === current ? 'step' : undefined}>
          <span aria-hidden="true">{i < current ? '✓' : i + 1}</span>{s}
        </li>
      ))}
    </ol>
  )
}

export function ProvisionFarmerPage({ organizationId, role }: { organizationId: string | null; role?: Role }) {
  const [done, setDone] = useState<ProvisionedFarmer | null>(null)
  if (!canManage(role) || !organizationId) {
    return <EmptyState icon="denied" title="Chỉ cán bộ quản lý HTX được thêm nông hộ" body="Tài khoản của bạn không có quyền cấp tài khoản nông hộ." />
  }
  return (
    <>
      <Breadcrumb items={[{ label: 'Tài khoản nông hộ', to: FARMERS_PATH }, { label: 'Thêm nông hộ' }]} />
      <PageHead eyebrow="Quản lý" title="Thêm nông hộ" meta={[<>Cấp tài khoản, gán nông hộ và thửa ruộng trong một lần</>]} />
      {done ? <Provisioned result={done} onAnother={() => setDone(null)} /> : <ProvisionForm organizationId={organizationId} onDone={setDone} />}
    </>
  )
}

function ProvisionForm({ organizationId, onDone }: { organizationId: string; onDone: (r: ProvisionedFarmer) => void }) {
  const [account, setAccount] = useState({ fullName: '', email: '', phone: '' })
  const [withFarm, setWithFarm] = useState(true)
  const [withPlot, setWithPlot] = useState(true)
  const farm = useFarmFields('farm.')
  const plot = usePlotFields('plot.')
  const [err, setErr] = useState<Record<string, string>>({})
  const [failure, setFailure] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const ids = { name: useId(), email: useId(), phone: useId() }
  const step = !withFarm ? 1 : !withPlot ? 2 : 3

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (pending) return
    const found: Record<string, string> = {}
    if (!account.fullName.trim()) found.fullName = 'Nhập họ và tên.'
    if (!EMAIL.test(account.email.trim())) found.email = 'Nhập email hợp lệ — đây là tên đăng nhập của nông hộ.'
    if (withFarm) Object.assign(found, farm.errors())
    if (withFarm && withPlot) Object.assign(found, plot.errors())
    setErr(found); setFailure(null)
    if (Object.keys(found).length) return
    setPending(true)
    try {
      onDone(await provisionFarmer(organizationId, {
        ...account, farm: withFarm ? farm.value : null, plot: withFarm && withPlot ? plot.value() : null,
      }))
    } catch (x) {
      setFailure(provisioningErrorMessage(x))
      setPending(false)
    }
  }

  return (
    <form className="acct-form acct-form--page" onSubmit={submit} noValidate aria-busy={pending || undefined}>
      <Steps current={step} />
      <Section title="1. Tài khoản đăng nhập" description="Tài khoản vai trò Nông dân của HTX, hoạt động ngay sau khi tạo.">
        <div className="acct-grid">
          <Field id={ids.name} label="Họ và tên" required error={err.fullName}><input id={ids.name} value={account.fullName} autoComplete="off" onChange={(e) => setAccount({ ...account, fullName: e.target.value })} /></Field>
          <Field id={ids.email} label="Email đăng nhập" required error={err.email}><input id={ids.email} type="email" value={account.email} autoComplete="off" onChange={(e) => setAccount({ ...account, email: e.target.value })} /></Field>
          <Field id={ids.phone} label="Số điện thoại" optional><input id={ids.phone} type="tel" value={account.phone} autoComplete="off" onChange={(e) => setAccount({ ...account, phone: e.target.value })} /></Field>
        </div>
      </Section>
      <Section title="2. Nông hộ">
        <label className="form-check"><input type="checkbox" checked={withFarm} onChange={(e) => setWithFarm(e.target.checked)} /> Tạo nông hộ cho tài khoản này (nông dân là chủ hộ)</label>
        {withFarm ? farm.render(err) : <p className="muted">Có thể tạo nông hộ sau trong danh sách Tài khoản nông hộ.</p>}
      </Section>
      <Section title="3. Thửa ruộng đầu tiên">
        <label className="form-check"><input type="checkbox" checked={withFarm && withPlot} disabled={!withFarm} onChange={(e) => setWithPlot(e.target.checked)} /> Ghi nhận thửa ruộng đầu tiên</label>
        {withFarm && withPlot ? plot.render(err) : <p className="muted">{withFarm ? 'Có thể gán thửa sau.' : 'Cần có nông hộ trước khi gán thửa.'}</p>}
      </Section>
      {failure && <Notice kind="error">{failure}</Notice>}
      <div className="acct-form__actions">
        <button type="button" className="btn btn--ghost" onClick={() => go(FARMERS_PATH)} disabled={pending}>Hủy</button>
        <button type="submit" className="btn btn--primary" disabled={pending}>{pending ? 'Đang tạo tài khoản…' : 'Tạo tài khoản nông hộ'}</button>
      </div>
    </form>
  )
}

function Provisioned({ result, onAnother }: { result: ProvisionedFarmer; onAnother: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try { await navigator.clipboard.writeText(`${result.email}\n${result.temporaryPassword}`); setCopied(true) } catch { setCopied(false) }
  }
  return (
    <section className="acct-done" aria-labelledby="acct-done-title">
      <Steps current={result.plotId ? 3 : result.farmId ? 2 : 1} />
      <h2 id="acct-done-title"><Ico name="check" size={18} /> Đã tạo tài khoản cho {result.fullName}</h2>
      <dl className="acct-cred">
        <div><dt>Email đăng nhập</dt><dd>{result.email}</dd></div>
        <div><dt>Mật khẩu tạm</dt><dd><code data-testid="temporary-password">{result.temporaryPassword}</code></dd></div>
      </dl>
      <Notice kind="warning">
        Mật khẩu tạm chỉ hiển thị một lần và không lưu ở đâu trong hệ thống. Hãy giao trực tiếp cho nông hộ;
        sau khi đăng nhập, nông hộ đổi mật khẩu trong mục <b>Tôi → Đổi mật khẩu</b>.
      </Notice>
      <div className="acct-form__actions acct-form__actions--start">
        <button type="button" className="btn btn--ghost" onClick={() => void copy()}>{copied ? 'Đã sao chép' : 'Sao chép thông tin đăng nhập'}</button>
        {result.plotId && <button type="button" className="btn btn--primary" onClick={() => go(`/plots/${result.plotId}`)}>Bắt đầu vụ cho thửa này <Ico name="arrow" size={14} /></button>}
        <button type="button" className="btn btn--ghost" onClick={onAnother}>Thêm nông hộ khác</button>
        <button type="button" className="btn btn--ghost" onClick={() => go(FARMERS_PATH)}>Về danh sách</button>
      </div>
    </section>
  )
}
