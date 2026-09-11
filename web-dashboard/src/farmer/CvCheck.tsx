import { useEffect, useRef, useState } from 'react'
import type { DiseaseLabel } from '../api/cv'
import { ApiError } from '../api/client'
import { getCvInferences, uploadAndInferLeaf, type CvInference } from '../api/cv'
import { dateTime } from '../format'
import { Async, Drawer, EmptyState, Notice, Section, Sheet, useAsync } from '../ui'
import type { SeasonContext } from './ActivityForms'

/**
 * M03 CV Farmer integration (brief FW M03 §19-25). Farmer-facing Vietnamese
 * labels are owned here, not by the backend's `label_vi` (kept for other
 * consumers, e.g. the Flutter contract) — this map matches the brief's
 * exact wording (§10), including "Lá khỏe" for `healthy`.
 */
const CV_LABEL_VI: Record<DiseaseLabel, string> = {
  rice_blast: 'Đạo ôn',
  bacterial_leaf_blight: 'Bạc lá',
  brown_spot: 'Đốm nâu',
  healthy: 'Lá khỏe',
}

function cvLabelVi(label: DiseaseLabel | null): string {
  return label ? CV_LABEL_VI[label] : 'Chưa thể xác định'
}

function pct(confidence: number): string {
  return `${Math.round(confidence * 100)}%`
}

function mapCvError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 'not_found') return 'Không tìm thấy vụ canh tác hoặc bạn không còn quyền truy cập.'
    if (err.status === 422) return err.message || 'Ảnh không hợp lệ.'
    if (err.status >= 500 || err.status === 0) return 'Không thể phân tích ảnh lúc này. Dữ liệu chưa được lưu.'
    return err.message || 'Không thể phân tích ảnh.'
  }
  return 'Không thể phân tích ảnh.'
}

/* --------------------------------------------------------- entry point */

export function CvCheckButton({ season, onChecked }: { season: SeasonContext; onChecked?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" className="btn btn--ghost" onClick={() => setOpen(true)}>Kiểm tra lá lúa</button>
      {open && (
        <CvCheckSheet
          season={season}
          onClose={() => setOpen(false)}
          onChecked={() => { onChecked?.() }}
        />
      )}
    </>
  )
}

/* -------------------------------------------------------------- upload sheet */

type Step = 'pick' | 'preview' | 'analyzing' | 'result' | 'error'

function CvCheckSheet({ season, onClose, onChecked }: { season: SeasonContext; onClose: () => void; onChecked: () => void }) {
  const [step, setStep] = useState<Step>('pick')
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [result, setResult] = useState<CvInference | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])

  function pickFile(f: File | null) {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setFile(f)
    setPreviewUrl(f ? URL.createObjectURL(f) : null)
    setStep(f ? 'preview' : 'pick')
  }

  async function analyze() {
    if (!file) return
    setStep('analyzing')
    setError(null)
    try {
      const inference = await uploadAndInferLeaf(season.id, file)
      setResult(inference)
      setStep('result')
      onChecked()
    } catch (err) {
      setError(mapCvError(err))
      setStep('error')
    }
  }

  function reset() {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setFile(null)
    setPreviewUrl(null)
    setResult(null)
    setError(null)
    setStep('pick')
  }

  return (
    <Sheet title="Kiểm tra lá lúa" subtitle={season.label} onClose={onClose} busy={step === 'analyzing'}>
      <div className="cv-check">
        {(step === 'pick' || step === 'preview' || step === 'analyzing') && (
          <>
            <label className="cv-check__picker">
              <span className="sr-only">Chọn ảnh lá lúa (JPEG hoặc PNG)</span>
              <input
                type="file" accept="image/jpeg,image/png" disabled={step === 'analyzing'}
                onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
              />
              {previewUrl ? (
                <img src={previewUrl} alt="Ảnh lá lúa đã chọn để phân tích" className="cv-check__preview" />
              ) : (
                <span className="cv-check__picker-label">Chọn ảnh</span>
              )}
            </label>
            {step !== 'analyzing' && (
              <ul className="cv-check__tips">
                <li>Ảnh nên rõ nét</li>
                <li>Đủ sáng</li>
                <li>Chụp gần một lá</li>
                <li>Lá chiếm phần lớn ảnh</li>
              </ul>
            )}
            {step === 'analyzing' && (
              <p className="cv-check__loading" aria-live="polite">Đang phân tích...</p>
            )}
            <div className="activity-form__actions">
              <button type="button" className="btn btn--ghost" onClick={onClose} disabled={step === 'analyzing'}>Hủy</button>
              <button type="button" className="btn" disabled={!file || step === 'analyzing'} onClick={analyze}>
                {step === 'analyzing' ? 'Đang phân tích…' : 'Phân tích ảnh'}
              </button>
            </div>
          </>
        )}

        {step === 'result' && result && <CvResultView result={result} onRetry={reset} onClose={onClose} />}

        {step === 'error' && (
          <>
            <Notice kind="error">{error}</Notice>
            <div className="activity-form__actions">
              <button type="button" className="btn btn--ghost" onClick={onClose}>Đóng</button>
              <button type="button" className="btn" onClick={() => setStep('preview')}>Thử lại</button>
            </div>
          </>
        )}
      </div>
    </Sheet>
  )
}

/* ------------------------------------------------------------------ result */

function CvResultView({ result, onRetry, onClose }: { result: CvInference; onRetry: () => void; onClose: () => void }) {
  if (result.uncertain) {
    return (
      <div className="cv-result cv-result--uncertain">
        <h3>Chưa thể xác định chắc chắn</h3>
        <p className="cv-result__confidence">Độ tin cậy: {pct(result.confidence)}</p>
        <p>Mô hình chưa đủ tự tin với ảnh này.</p>
        <div className="cv-result__tips">
          <p>Hãy thử:</p>
          <ul>
            <li>Chụp gần hơn</li>
            <li>Đủ sáng</li>
            <li>Chỉ một lá trong khung hình</li>
          </ul>
        </div>
        <div className="activity-form__actions">
          <button type="button" className="btn btn--ghost" onClick={onClose}>Đóng</button>
          <button type="button" className="btn" onClick={onRetry}>Chụp/chọn ảnh khác</button>
        </div>
      </div>
    )
  }
  return (
    <div className="cv-result cv-result--confident">
      <h3>Kết quả nhận diện</h3>
      <p className="cv-result__label">{cvLabelVi(result.label)}</p>
      <p className="cv-result__confidence">Độ tin cậy: {pct(result.confidence)}</p>
      <Notice kind="info">Kết quả hỗ trợ nhận diện từ mô hình AI. Chưa được xác nhận thực địa.</Notice>
      <div className="activity-form__actions">
        <button type="button" className="btn btn--ghost" onClick={onClose}>Đóng</button>
        <button type="button" className="btn" onClick={onRetry}>Kiểm tra ảnh khác</button>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ history */

export function CvHistorySection({ seasonId, reloadKey }: { seasonId: string; reloadKey?: number }) {
  const state = useAsync(() => getCvInferences(seasonId), [seasonId, reloadKey])
  const [open, setOpen] = useState<CvInference | null>(null)
  return (
    <Section title="Kiểm tra gần đây" description="Kết quả hỗ trợ nhận diện từ mô hình AI — chưa xác nhận thực địa.">
      <Async state={state} skeleton="table" isEmpty={(items) => items.length === 0} empty={<EmptyState icon="🌿" title="Chưa có lần kiểm tra lá nào." />}>
        {(items) => (
          <div className="cv-history">
            {[...items].sort((a, b) => b.createdAt.localeCompare(a.createdAt)).map((item) => (
              <button key={item.id} type="button" className="cv-history__item" onClick={() => setOpen(item)}>
                <span className="cv-history__label">{item.uncertain ? 'Chưa chắc chắn' : cvLabelVi(item.label)}</span>
                <span className="cv-history__confidence">{pct(item.confidence)}</span>
                <time>{dateTime(item.createdAt)}</time>
              </button>
            ))}
          </div>
        )}
      </Async>
      {open && (
        <Drawer title={open.uncertain ? 'Chưa chắc chắn' : cvLabelVi(open.label)} subtitle={dateTime(open.createdAt)} onClose={() => setOpen(null)}>
          <dl className="dl" style={{ gridTemplateColumns: '1fr' }}>
            <div><dt>Độ tin cậy</dt><dd>{pct(open.confidence)}</dd></div>
            <div><dt>Trạng thái</dt><dd>{open.uncertain ? 'Chưa đủ tin cậy' : 'Đã nhận diện'}</dd></div>
          </dl>
          <Notice kind="info">Kết quả hỗ trợ nhận diện từ mô hình AI (baseline, chưa xác nhận thực địa).</Notice>
        </Drawer>
      )}
    </Section>
  )
}

/* -------------------------------------------------------------- home summary */

export function CvHomeSummaryCard({ seasonId, reloadKey }: { seasonId: string; reloadKey?: number }) {
  const state = useAsync(() => getCvInferences(seasonId), [seasonId, reloadKey])
  const latest = state.data ? [...state.data].sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0] : undefined
  if (state.loading || !latest) return null
  return (
    <section className="farmer-muted-card cv-summary-card">
      <h2>Kiểm tra lá gần nhất</h2>
      <p>{latest.uncertain ? `Chưa chắc chắn · ${pct(latest.confidence)}` : `${cvLabelVi(latest.label)} · ${pct(latest.confidence)}`}</p>
      <small>{dateTime(latest.createdAt)}</small>
    </section>
  )
}
