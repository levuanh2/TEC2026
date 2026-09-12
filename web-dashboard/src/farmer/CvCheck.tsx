import { useEffect, useState } from 'react'
import type { DiseaseLabel } from '../api/cv'
import { ApiError } from '../api/client'
import { uploadAndInferLeaf, type CvInference } from '../api/cv'
import { dateTime } from '../format'
import { invalidateQueries, keys } from './data'
import { Ico } from './icons'
import { Chip, Empty, ErrorPanel, FarmerDrawer, FarmerSheet, IconTile, Section, Sk, SkBlock } from './kit'
import { useCvHistory } from './scope'
import type { SeasonContext } from './ActivityForms'

/* M03 leaf check (experimental baseline model). Every field shown is exactly
 * what the backend returned; below the confidence threshold no disease label
 * is ever forced. */

const CV_LABEL_VI: Record<DiseaseLabel, string> = {
  rice_blast: 'Đạo ôn',
  bacterial_leaf_blight: 'Bạc lá',
  brown_spot: 'Đốm nâu',
  healthy: 'Lá khỏe',
}
const cvLabelVi = (label: DiseaseLabel | null) => (label ? CV_LABEL_VI[label] : 'Chưa thể xác định')
const pct = (v: number) => `${Math.round(v * 100)}%`
const DISCLAIMER = 'Kết quả chỉ mang tính hỗ trợ, chưa được xác nhận thực địa.'

function mapCvError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 'not_found') return 'Không tìm thấy vụ canh tác hoặc bạn không còn quyền truy cập.'
    if (err.status === 422) return err.message || 'Ảnh không hợp lệ.'
    if (err.status >= 500 || err.status === 0) return 'Không thể phân tích ảnh lúc này. Dữ liệu chưa được lưu.'
    return err.message || 'Không thể phân tích ảnh.'
  }
  return 'Không thể phân tích ảnh.'
}

function Confidence({ value, threshold }: { value: number; threshold?: number }) {
  return (
    <div className="fw-conf">
      <div className="fw-conf__row"><span>Độ tin cậy</span><span>{pct(value)}</span></div>
      <div className="fw-conf__bar" role="img" aria-label={`Độ tin cậy ${pct(value)}${threshold != null ? `, ngưỡng ${pct(threshold)}` : ''}`}><i style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} /></div>
    </div>
  )
}

/* --------------------------------------------------------- entry point */

export function CvCheckButton({ season, variant = 'soft' }: { season: SeasonContext; variant?: 'soft' | 'primary' }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" className={`fw-btn${variant === 'soft' ? ' fw-btn--soft' : ''}`} onClick={() => setOpen(true)}><Ico name="cv" />Kiểm tra lá lúa</button>
      {open && <CvCheckSheet season={season} onClose={() => setOpen(false)} />}
    </>
  )
}

/* -------------------------------------------------------------- upload sheet */

type Step = 'pick' | 'preview' | 'analyzing' | 'result' | 'error'

function CvCheckSheet({ season, onClose }: { season: SeasonContext; onClose: () => void }) {
  const [step, setStep] = useState<Step>('pick')
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [result, setResult] = useState<CvInference | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [over, setOver] = useState(false)

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
      invalidateQueries(keys.cv(season.id))
    } catch (err) {
      setError(mapCvError(err))
      setStep('error')
    }
  }

  function reset() {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setFile(null); setPreviewUrl(null); setResult(null); setError(null); setStep('pick')
  }

  const picking = step === 'pick' || step === 'preview' || step === 'analyzing'
  return (
    <FarmerSheet title="Kiểm tra lá lúa" subtitle={season.label} icon="cv" tone="info" onClose={onClose} busy={step === 'analyzing'} wide>
      <div className="fw-cv cv-check">
        {picking && (
          <div className="fw-cv__layout">
            <label
              className={`fw-cv__drop cv-check__picker${over ? ' is-over' : ''}`}
              onDragEnter={() => setOver(true)} onDragLeave={() => setOver(false)} onDrop={() => setOver(false)}
            >
              <span className="sr-only">Chọn ảnh lá lúa (JPEG hoặc PNG)</span>
              <input type="file" accept="image/jpeg,image/png" disabled={step === 'analyzing'} onChange={(e) => pickFile(e.target.files?.[0] ?? null)} />
              {previewUrl ? (
                <img src={previewUrl} alt="Ảnh lá lúa đã chọn để phân tích" className="fw-cv__preview" />
              ) : (
                <>
                  <IconTile name="image" tone="forest" size="lg" />
                  <b>Chọn ảnh hoặc kéo thả vào đây</b>
                  <small>JPEG hoặc PNG · chụp gần một lá lúa</small>
                </>
              )}
            </label>
            <div className="fw-cv__guide">
              <h4>Để kết quả rõ ràng hơn</h4>
              <ul>
                {['Ảnh nên rõ nét', 'Đủ sáng', 'Chụp gần một lá', 'Lá chiếm phần lớn ảnh'].map((tip) => <li key={tip}><Ico name="check" />{tip}</li>)}
              </ul>
              {file && <p className="fw-note">Đã chọn: <b>{file.name}</b></p>}
            </div>
          </div>
        )}
        {step === 'analyzing' && <p className="fw-cv__analyzing" aria-live="polite"><Ico name="spinner" className="fw-spin" />Đang phân tích ảnh…</p>}

        {step === 'result' && result && <CvResultView result={result} onRetry={reset} onClose={onClose} />}

        {step === 'error' && (
          <div className="fw-cv__result fw-cv__result--uncertain cv-result">
            <h3>Không phân tích được ảnh</h3>
            <p>{error}</p>
            <div className="fw-rec__actions">
              <button type="button" className="fw-btn fw-btn--ghost" onClick={onClose}>Đóng</button>
              <button type="button" className="fw-btn" onClick={() => setStep('preview')}>Thử lại</button>
            </div>
          </div>
        )}

        <p className="fw-disclaimer"><Ico name="info" />{DISCLAIMER}</p>

        {picking && (
          <div className="fw-form__footer">
            <button type="button" className="fw-btn fw-btn--ghost" onClick={onClose} disabled={step === 'analyzing'}>Hủy</button>
            <button type="button" className="fw-btn" disabled={!file || step === 'analyzing'} onClick={() => void analyze()}>
              {step === 'analyzing' ? 'Đang phân tích…' : 'Phân tích ảnh'}
            </button>
          </div>
        )}
      </div>
    </FarmerSheet>
  )
}

/* ------------------------------------------------------------------ result */

function CvResultView({ result, onRetry, onClose }: { result: CvInference; onRetry: () => void; onClose: () => void }) {
  return (
    <div className={`fw-cv__result cv-result${result.uncertain ? ' fw-cv__result--uncertain cv-result--uncertain' : ' cv-result--confident'}`}>
      <h3>{result.uncertain ? 'Chưa thể xác định chắc chắn' : 'Kết quả nhận diện'}</h3>
      <p className="fw-cv__label">{result.uncertain ? 'Chưa đủ tin cậy để gán nhãn' : cvLabelVi(result.label)}</p>
      <Confidence value={result.confidence} threshold={result.thresholdUsed} />
      {result.uncertain && (
        <div>
          <p>Mô hình chưa đủ tự tin với ảnh này. Hãy thử:</p>
          <ul className="fw-cv__tips"><li>Chụp gần hơn</li><li>Đủ sáng</li><li>Chỉ một lá trong khung hình</li></ul>
        </div>
      )}
      <p className="fw-cv__meta">Mô hình thử nghiệm {result.modelVersion} · ngưỡng tin cậy {pct(result.thresholdUsed)}</p>
      <div className="fw-rec__actions">
        <button type="button" className="fw-btn fw-btn--ghost" onClick={onClose}>Đóng</button>
        <button type="button" className="fw-btn" onClick={onRetry}>{result.uncertain ? 'Chụp/chọn ảnh khác' : 'Kiểm tra ảnh khác'}</button>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ history */

export function CvHistorySection({ seasonId }: { seasonId: string | null }) {
  const state = useCvHistory(seasonId)
  const [open, setOpen] = useState<CvInference | null>(null)
  const items = [...(state.data ?? [])].sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  return (
    <Section title="Kiểm tra gần đây" icon="history" tone="info" description="Kết quả hỗ trợ nhận diện từ mô hình AI — chưa xác nhận thực địa.">
      {state.loading ? (
        <SkBlock label="Đang tải lịch sử kiểm tra" className="fw-cvhist">
          {[0, 1].map((i) => <div key={i} className="fw-cvhist__item"><Sk w={34} h={34} r={10} /><Sk w="40%" h={13} /><Sk w="80%" h={8} /><Sk w={90} h={11} /></div>)}
        </SkBlock>
      ) : state.error ? (
        <ErrorPanel error={state.error} onRetry={state.reload} />
      ) : !items.length ? (
        <Empty icon="cv" tone="info" title="Chưa có lần kiểm tra lá nào." body="Kết quả các lần kiểm tra lá của vụ này sẽ xuất hiện ở đây." />
      ) : (
        <div className="fw-cvhist">
          {items.map((item) => (
            <button key={item.id} type="button" className="fw-cvhist__item cv-history__item" onClick={() => setOpen(item)}>
              <IconTile name={item.uncertain ? 'warning' : 'cv'} tone={item.uncertain ? 'amber' : 'info'} size="sm" />
              <b>{item.uncertain ? 'Chưa chắc chắn' : cvLabelVi(item.label)}</b>
              <Confidence value={item.confidence} />
              <time dateTime={item.createdAt}>{dateTime(item.createdAt)}</time>
            </button>
          ))}
        </div>
      )}
      {open && (
        <FarmerDrawer title={open.uncertain ? 'Chưa chắc chắn' : cvLabelVi(open.label)} subtitle={dateTime(open.createdAt)} icon={<IconTile name="cv" tone="info" />} onClose={() => setOpen(null)}>
          <Confidence value={open.confidence} threshold={open.thresholdUsed} />
          <dl className="fw-detail">
            <div><dt>Trạng thái</dt><dd>{open.uncertain ? 'Chưa đủ tin cậy' : 'Đã nhận diện'}</dd></div>
            <div><dt>Ngưỡng tin cậy</dt><dd>{pct(open.thresholdUsed)}</dd></div>
            <div><dt>Phiên bản mô hình</dt><dd>{open.modelVersion}</dd></div>
          </dl>
          <p className="fw-disclaimer" style={{ marginTop: 16 }}><Ico name="info" />Kết quả hỗ trợ nhận diện từ mô hình AI thử nghiệm, chưa xác nhận thực địa.</p>
        </FarmerDrawer>
      )}
    </Section>
  )
}

/* --------------------------------------------------------- shortcut card */

export function CvPreviewCard({ season, seasonId }: { season: SeasonContext | null; seasonId: string | null }) {
  const state = useCvHistory(seasonId)
  const latest = [...(state.data ?? [])].sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0]
  return (
    <section className="fw-cvcard" aria-labelledby="fw-cvcard-title">
      <IconTile name="cv" tone="info" size="lg" />
      <div>
        <h3 id="fw-cvcard-title">Kiểm tra lá lúa bằng ảnh</h3>
        <p>Chụp hoặc chọn ảnh một lá để nhận diện nhanh bằng mô hình AI thử nghiệm.</p>
        {latest && (
          <p className="fw-cvcard__latest">
            <span>Lần gần nhất:</span>
            <Chip tone={latest.uncertain ? 'amber' : 'info'}>{latest.uncertain ? 'Chưa chắc chắn' : cvLabelVi(latest.label)} · {pct(latest.confidence)}</Chip>
            <small className="fw-note">{dateTime(latest.createdAt)}</small>
          </p>
        )}
      </div>
      {season ? <CvCheckButton season={season} /> : <span className="fw-note">Cần một vụ đang canh tác</span>}
    </section>
  )
}
