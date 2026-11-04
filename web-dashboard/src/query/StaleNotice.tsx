import { Ico } from '../icons'

const time = (ms: number) => new Date(ms).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })

/** The one way a page says "these figures are from an earlier read and the
 *  refresh just failed". Cached data is never presented as current without it. */
export function StaleNotice({ error, updatedAt, onRetry, what = 'dữ liệu' }: {
  error?: string; updatedAt: number; onRetry: () => void; what?: string
}) {
  if (!error) return null
  return (
    <p className="ops-error stale-notice" role="alert" data-testid="stale-notice">
      <Ico name="warning" size={14} />
      <span>
        Không làm mới được {what}: {error} Đang hiển thị {what} đọc lúc {time(updatedAt)} — có thể đã cũ.
      </span>
      <button type="button" className="btn btn--ghost btn--sm" onClick={onRetry}>Thử lại</button>
    </p>
  )
}
