import { useId, useState } from 'react'
import { ApiError } from '../api/client'
import { updateSeasonMethodology } from '../api/crops'
import { Notice, Section } from '../ui'
import type { CropSeason, IpccPreSeasonRegime, IpccWaterRegime } from '../types'

/**
 * "Thông tin phương pháp tính" — the season-level IPCC inputs the Carbon engine
 * reads off `crop_seasons`.
 *
 * These are not journal activities: a season has exactly one water regime, one
 * pre-season regime and one cultivation length, so they belong on the season and
 * not on a dated record. Before this panel existed they could only be written by
 * the Flutter app (which upserts `crop_seasons` through PostgREST), which left a
 * Farmer Web-only user unable to obtain a Carbon result at all.
 *
 * No Carbon arithmetic happens here. The panel collects inputs and reports what
 * is still missing; every factor and formula stays server-side.
 */

const WATER_REGIMES: { value: IpccWaterRegime; label: string; help: string }[] = [
  { value: 'irrigated_continuous_flooding', label: 'Tưới — ngập liên tục', help: 'Ruộng giữ nước gần như suốt vụ, không rút cạn giữa vụ.' },
  { value: 'irrigated_single_drainage', label: 'Tưới — rút nước 1 lần', help: 'Có đúng một lần tháo cạn ruộng trong vụ.' },
  { value: 'irrigated_multiple_drainage', label: 'Tưới — rút nước nhiều lần (gồm AWD)', help: 'Ngập – khô xen kẽ, hoặc tháo cạn từ 2 lần trở lên.' },
  { value: 'rainfed_regular', label: 'Nhờ nước trời — thường xuyên', help: 'Không chủ động tưới; ruộng ngập theo mưa.' },
  { value: 'rainfed_drought_prone', label: 'Nhờ nước trời — dễ hạn', help: 'Phụ thuộc nước mưa và thường thiếu nước.' },
  { value: 'deep_water', label: 'Lúa nước sâu', help: 'Mực nước trên ruộng thường xuyên sâu hơn 50 cm.' },
  { value: 'upland', label: 'Lúa cạn', help: 'Ruộng không ngập nước trong thời gian đáng kể.' },
]

const PRE_SEASON_REGIMES: { value: IpccPreSeasonRegime; label: string; help: string }[] = [
  { value: 'non_flooded_pre_season_lt_180d', label: 'Không ngập, dưới 180 ngày trước vụ', help: 'Thường gặp khi làm 2 vụ lúa/năm.' },
  { value: 'non_flooded_pre_season_gt_180d', label: 'Không ngập, trên 180 ngày trước vụ', help: 'Ruộng để khô dài trước khi vào vụ.' },
  { value: 'flooded_pre_season_gt_30d', label: 'Có ngập từ 30 ngày trở lên trước vụ', help: 'Làm tăng phát thải CH₄ hơn gấp đôi — cần khai đúng.' },
  { value: 'non_flooded_pre_season_gt_365d', label: 'Không ngập, trên 365 ngày trước vụ', help: 'Luân canh cây trồng cạn rồi quay lại lúa.' },
]

type Draft = { water: string; pre: string; days: string }

const toDraft = (s: CropSeason): Draft => ({
  water: s.ipccWaterRegime ?? '',
  pre: s.preSeasonWaterRegime ?? '',
  days: s.cultivationDays == null ? '' : String(s.cultivationDays),
})

/** Empty string means "chưa ghi nhận" and is sent as null — never coerced to 0. */
const daysOrNull = (v: string): number | null => {
  const t = v.trim()
  if (t === '') return null
  const n = Number(t)
  return Number.isFinite(n) ? n : null
}

function Choice<T extends string>({
  legend, hint, options, value, onChange,
}: {
  legend: string; hint: string
  options: { value: T; label: string; help: string }[]
  value: string; onChange: (v: string) => void
}) {
  const name = useId()
  return (
    <fieldset className="form-fieldset">
      <legend>{legend}</legend>
      <p className="form-fieldset__hint">{hint}</p>
      {options.map((o) => (
        <label key={o.value} className="form-choice">
          <input
            type="radio" name={name} value={o.value} checked={value === o.value}
            onChange={() => onChange(o.value)}
          />
          <span>
            <strong>{o.label}</strong>
            <small>{o.help}</small>
          </span>
        </label>
      ))}
    </fieldset>
  )
}

export function SeasonMethodologyPanel({
  season, canEdit, onSaved,
}: {
  season: CropSeason
  canEdit: boolean
  onSaved?: (updated: CropSeason) => void
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(season))
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<{ busy: boolean; error?: string; saved?: boolean }>({ busy: false })

  const missing = [
    !season.ipccWaterRegime && 'Chế độ nước trong vụ',
    !season.preSeasonWaterRegime && 'Chế độ nước trước vụ',
  ].filter(Boolean) as string[]

  async function save() {
    setState({ busy: true })
    try {
      const updated = await updateSeasonMethodology(season.id, {
        ipccWaterRegime: (draft.water || null) as IpccWaterRegime | null,
        preSeasonWaterRegime: (draft.pre || null) as IpccPreSeasonRegime | null,
        cultivationDays: daysOrNull(draft.days),
      })
      setState({ busy: false, saved: true })
      onSaved?.(updated)
    } catch (e) {
      const api = e as ApiError
      setState({
        busy: false,
        error: api?.status === 404
          ? 'Bạn không có quyền sửa thông tin phương pháp tính của vụ này.'
          : e instanceof Error ? e.message : 'Không lưu được.',
      })
    }
  }

  return (
    <Section
      title="Thông tin phương pháp tính"
      description="Dữ liệu chế độ nước theo phân loại IPCC — bắt buộc để tính được phát thải CH₄ của vụ."
    >
      <div className="stack">
        {missing.length > 0 ? (
          <Notice kind="warning">
            Chưa tính được carbon vì còn thiếu: <strong>{missing.join(' · ')}</strong>.
            {canEdit ? ' Bổ sung bên dưới rồi bấm Lưu.' : ' Hãy liên hệ chủ hộ hoặc cán bộ hợp tác xã để bổ sung.'}
          </Notice>
        ) : (
          <Notice kind="success">Đã đủ thông tin chế độ nước để tính phát thải.</Notice>
        )}

        {canEdit && (
          <>
            <button className="btn btn--ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
              {open ? 'Ẩn thông tin phương pháp tính' : 'Khai báo thông tin phương pháp tính'}
            </button>
            {open && (
              <div className="stack">
                <Choice
                  legend="Chế độ nước trong vụ"
                  hint="Cách ruộng được giữ nước trong vụ này. Ảnh hưởng trực tiếp tới lượng khí CH₄ phát thải."
                  options={WATER_REGIMES} value={draft.water}
                  onChange={(v) => setDraft({ ...draft, water: v })}
                />
                <Choice
                  legend="Chế độ nước trước vụ"
                  hint="Tình trạng ngập nước của ruộng trong khoảng thời gian TRƯỚC khi bắt đầu vụ này."
                  options={PRE_SEASON_REGIMES} value={draft.pre}
                  onChange={(v) => setDraft({ ...draft, pre: v })}
                />
                <div className="form-field">
                  <label htmlFor="cultivation-days">
                    Số ngày canh tác <small>Không bắt buộc · để trống nếu đã có ngày gieo sạ và ngày thu hoạch</small>
                  </label>
                  <input
                    id="cultivation-days" type="number" inputMode="numeric" step="1" min="1"
                    value={draft.days} onChange={(e) => setDraft({ ...draft, days: e.target.value })}
                  />
                </div>
                {state.error && <Notice kind="error">{state.error}</Notice>}
                {state.saved && !state.error && <Notice kind="success">Đã lưu thông tin phương pháp tính.</Notice>}
                <div>
                  <button className="btn btn--primary" onClick={save} disabled={state.busy}>
                    {state.busy ? 'Đang lưu…' : 'Lưu'}
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </Section>
  )
}
