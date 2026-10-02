import { useState, type FormEvent } from 'react'
import type { Session } from '@supabase/supabase-js'
import { replaceTemporaryPassword, signOut } from '../api/auth'
import { passwordProblems } from '../farmer/ChangePassword'
import { Notice } from '../ui'

/* Forced first login. An account the cooperative provisioned starts with a
 * temporary password the manager has seen; until it is replaced the server
 * refuses every business request (403 `password_change_required`, and the
 * database returns nothing), so this is the only screen -- plus sign-out. The
 * flag is cleared by the server, never here. */
export function ForcedPasswordChange({ session, done }: { session: Session; done: (s: Session) => void }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    const current = String(f.get('current') ?? '')
    const next = String(f.get('next') ?? '')
    const problem = !current ? 'Nhập mật khẩu tạm HTX đã cấp.' : passwordProblems(next, String(f.get('confirm') ?? ''))
    setError(problem ?? '')
    if (problem) return
    setBusy(true)
    try {
      done(await replaceTemporaryPassword(current, next))
    } catch (x) {
      setError(x instanceof Error ? x.message : 'Chưa đổi được mật khẩu. Vui lòng thử lại.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login">
      <section className="login-card" data-testid="forced-password-change">
        <p className="eyebrow">AGRICARBON</p>
        <h1>Đặt mật khẩu của bạn</h1>
        <p>
          Tài khoản {session.user.email ? <strong>{session.user.email}</strong> : null} đang dùng mật khẩu tạm do HTX cấp.
          Hãy đặt mật khẩu riêng để tiếp tục — người khác đã từng thấy mật khẩu tạm này.
        </p>
        <form onSubmit={submit} noValidate>
          <label>
            Mật khẩu tạm
            <input name="current" type="password" autoComplete="current-password" required />
          </label>
          <label>
            Mật khẩu mới
            <input name="next" type="password" autoComplete="new-password" required />
          </label>
          <label>
            Nhập lại mật khẩu mới
            <input name="confirm" type="password" autoComplete="new-password" required />
          </label>
          <p className="muted">Ít nhất 8 ký tự, có chữ hoa, chữ thường và số.</p>
          {error && <Notice kind="error">{error}</Notice>}
          <button className="btn" disabled={busy}>{busy ? 'Đang lưu…' : 'Lưu mật khẩu và tiếp tục'}</button>
          <button type="button" className="btn btn--ghost" onClick={() => void signOut()} disabled={busy}>Đăng xuất</button>
        </form>
      </section>
    </main>
  )
}
