import { useId, useState, type FormEvent } from 'react'
import { changePassword } from '../api/auth'
import { Ico } from './icons'
import { Section } from './kit'

/* "Đổi mật khẩu" — a cooperative-provisioned account starts with a temporary
 * password handed over by the manager; this is where the farmer replaces it. */

export function passwordProblems(next: string, confirm: string): string | null {
  if (next.length < 8) return 'Mật khẩu mới cần ít nhất 8 ký tự.'
  if (!/[a-z]/.test(next) || !/[A-Z]/.test(next) || !/\d/.test(next)) return 'Mật khẩu mới cần có chữ hoa, chữ thường và số.'
  if (next !== confirm) return 'Hai lần nhập mật khẩu mới không khớp.'
  return null
}

export function ChangePasswordSection({ email }: { email: string | null }) {
  const [v, set] = useState({ current: '', next: '', confirm: '' })
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [pending, setPending] = useState(false)
  const ids = { current: useId(), next: useId(), confirm: useId() }
  if (!email) return null

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (pending) return
    setDone(false)
    const problem = !v.current ? 'Nhập mật khẩu hiện tại.' : passwordProblems(v.next, v.confirm)
    setError(problem)
    if (problem) return
    setPending(true)
    try {
      await changePassword(email!, v.current, v.next)
      set({ current: '', next: '', confirm: '' })
      setDone(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Chưa đổi được mật khẩu. Vui lòng thử lại.')
    } finally {
      setPending(false)
    }
  }

  return (
    <Section title="Đổi mật khẩu" icon="denied" description="Nếu bạn đang dùng mật khẩu tạm do HTX cấp, hãy đổi sang mật khẩu của riêng bạn.">
      <form className="fw-password" onSubmit={submit} noValidate>
        <div className="form-field"><label htmlFor={ids.current}>Mật khẩu hiện tại</label>
          <input id={ids.current} type="password" autoComplete="current-password" value={v.current} onChange={(e) => set({ ...v, current: e.target.value })} /></div>
        <div className="form-field"><label htmlFor={ids.next}>Mật khẩu mới</label>
          <input id={ids.next} type="password" autoComplete="new-password" value={v.next} onChange={(e) => set({ ...v, next: e.target.value })} /></div>
        <div className="form-field"><label htmlFor={ids.confirm}>Nhập lại mật khẩu mới</label>
          <input id={ids.confirm} type="password" autoComplete="new-password" value={v.confirm} onChange={(e) => set({ ...v, confirm: e.target.value })} /></div>
        {error && <p className="form-field__error" role="alert"><Ico name="warning" />{error}</p>}
        {done && <p className="fw-note" role="status"><Ico name="check" />Đã đổi mật khẩu. Lần sau đăng nhập bằng mật khẩu mới.</p>}
        <div><button type="submit" className="fw-btn" disabled={pending}>{pending ? 'Đang đổi…' : 'Đổi mật khẩu'}</button></div>
      </form>
    </Section>
  )
}
