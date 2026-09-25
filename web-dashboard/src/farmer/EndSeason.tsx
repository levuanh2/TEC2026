import { useId, useState } from 'react'
import type { FarmerScope } from '../api/farms'
import { endCropSeason, endSeasonErrorMessage } from '../api/crops'
import type { CropSeason } from '../types'
import { invalidateQueries, keys, peekQuery, setQueryData } from './data'
import { Ico } from './icons'
import { FarmerConfirm } from './kit'

/* "Kết thúc vụ" on Farmer Web. After it the season's journal is history: the
 * database refuses new records from every client (Web and the Flutter app),
 * while metrics and Carbon stay as they are. A finished season is not reopened. */

export function EndSeasonButton({ season }: { season: CropSeason }) {
  const [open, setOpen] = useState(false)
  const [date, setDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dateId = useId()

  async function confirm() {
    if (busy) return
    setBusy(true); setError(null)
    try {
      const ended = await endCropSeason(season.id, date || null)
      const scope = peekQuery<FarmerScope>(keys.scope)
      if (scope) setQueryData<FarmerScope>(keys.scope, { ...scope, seasons: scope.seasons.map((s) => (s.id === season.id ? { ...s, ...ended } : s)) })
      invalidateQueries(keys.scope)
      setOpen(false)
    } catch (err) {
      setError(endSeasonErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button type="button" className="fw-btn fw-btn--ghost fw-btn--sm" onClick={() => setOpen(true)}><Ico name="harvest" />Kết thúc vụ</button>
      {open && (
        <FarmerConfirm
          title={`Kết thúc vụ ${season.name}?`}
          confirmLabel="Kết thúc vụ"
          icon="harvest"
          busy={busy}
          onCancel={() => { setOpen(false); setError(null) }}
          onConfirm={() => void confirm()}
          body={<>
            <p>Sau khi kết thúc, nhật ký của vụ chỉ còn để xem: không ghi, sửa hay xóa hoạt động nữa, kể cả từ ứng dụng điện thoại. Hiệu suất và Carbon vẫn giữ nguyên. Vụ đã kết thúc không mở lại được.</p>
            <div className="form-field">
              <label htmlFor={dateId}>Ngày thu hoạch <span className="form-field__opt">Không bắt buộc</span></label>
              <input id={dateId} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </div>
            {error && <p className="form-field__error" role="alert">{error}</p>}
          </>}
        />
      )}
    </>
  )
}
