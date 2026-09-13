import { useState } from 'react'
import { Ico } from '../icons'
import { listMrvCases, getMrvCase, listMrvEvidence, createMrvJsonExport, createMrvXlsxExport, createMrvPdfExport, downloadMrvExport, listMrvExports, type MrvCase, type MrvEvidence, type MrvExportFormat, type MrvExportHistoryItem, type MrvExportResult } from '../api/mrv'
import { usingMockData } from '../api/farms'
import { date, dateTime, shortHash } from '../format'
import { presentMrvStatus, mrvBadgeTone, mrvProgress, MRV_STEP_NAMES } from '../utils/mrvPresentation'
import { Async, Badge, EmptyState, Hero, Notice, PageHead, Progress, Section, useAsync } from '../ui'
import type { Role } from '../types'

type MrvStep = { stepNo: number; name: string; status: string; startedAt: string | null; completedAt: string | null; notes: string | null }

const MOCK_STEPS: MrvStep[] = MRV_STEP_NAMES.map((name, i) => ({
  stepNo: i + 1,
  name,
  status: i === 0 ? 'completed' : i === 1 ? 'in_progress' : 'not_started',
  startedAt: i <= 1 ? '2026-05-02' : null,
  completedAt: i === 0 ? '2026-05-06' : null,
  notes: null,
}))

export function MrvPage({ role }: { role?: Role } = {}) {
  const state = useAsync<{ mrvCase: MrvCase | null; evidence: MrvEvidence[] }>(async () => {
    if (usingMockData) return { mrvCase: null, evidence: [] }
    const cases = await listMrvCases()
    if (!cases[0]) return { mrvCase: null, evidence: [] }
    const [mrvCase, evidence] = await Promise.all([
      getMrvCase(cases[0].caseId),
      listMrvEvidence(cases[0].caseId).catch(() => [] as MrvEvidence[]),
    ])
    return { mrvCase, evidence }
  }, [])

  return (
    <>
      <PageHead eyebrow="MRV" title="Hồ sơ MRV" meta={[<>Đo đạc – Báo cáo – Thẩm định theo 6 bước</>]} />
      <Notice kind="warning">
        Bản mẫu / demo — chưa phải biểu mẫu chính thức hoặc báo cáo đã được cơ quan quản lý phê duyệt.
      </Notice>

      <Async
        state={state}
        isEmpty={(d) => !usingMockData && !d.mrvCase}
        empty={<EmptyState icon="task" title="Chưa có hồ sơ MRV nào trong phạm vi" />}
      >
        {({ mrvCase, evidence }) => {
          const steps: MrvStep[] = mrvCase?.steps?.length ? (mrvCase.steps as MrvStep[]) : MOCK_STEPS
          const p = mrvProgress(steps)
          const currentIdx = steps.findIndex((s) => s.status === 'in_progress')
          return (
            <div className="stack" style={{ marginTop: 16 }}>
              {mrvCase && (
                <Hero
                  eyebrow={`${mrvCase.caseCode} · Kỳ ${date(mrvCase.periodStart)} – ${date(mrvCase.periodEnd)}`}
                  title={mrvCase.name}
                  meta={[<Badge tone={mrvBadgeTone(mrvCase.status)} dot>{presentMrvStatus(mrvCase.status).label}</Badge>]}
                  stats={[
                    { label: 'Bước hoàn thành', value: `${p.done}/${p.total}` },
                    { label: 'Lô sản xuất', value: mrvCase.batchCount },
                    { label: 'Minh chứng', value: mrvCase.evidenceCount },
                  ]}
                />
              )}
              <div className="card card--pad">
                <Progress value={p.done} max={p.total} unitLabel={`bước hoàn thành · ${p.inProgress} đang thực hiện`} />
              </div>

              <Section title="Tiến trình 6 bước" description="Đo đạc – Báo cáo – Thẩm định, theo đúng thứ tự bắt buộc">
                <ol className="stepper">
                  {steps.map((s, i) => {
                    const st = presentMrvStatus(s.status)
                    const cls = s.status === 'completed' ? 'is-done' : i === currentIdx ? 'is-current' : ''
                    return (
                      <li key={s.stepNo} className={`step ${cls}`}>
                        <span className="step__marker" aria-hidden="true">
                          {s.status === 'completed' ? <Ico name="tick" size={12} /> : s.stepNo}
                        </span>
                        <div className="step__body">
                          <b>{s.name}</b>
                          <div className="step__meta">
                            <Badge tone={mrvBadgeTone(s.status)}>{st.label}</Badge>
                            {s.startedAt && <span>Bắt đầu {date(s.startedAt)}</span>}
                            {s.completedAt && <span>Hoàn thành {date(s.completedAt)}</span>}
                          </div>
                          {s.notes && <p className="muted" style={{ fontSize: 'var(--fs-caption)' }}>{s.notes}</p>}
                          <StepEvidence items={evidence.filter((e) => e.stepNo === s.stepNo)} />
                        </div>
                      </li>
                    )
                  })}
                </ol>
              </Section>

              <Section title="Xuất dữ liệu" description="Snapshot dữ liệu MRV và các bản kết xuất từ đúng snapshot đó">
                {/* Only offered for a real case the viewer may actually export:
                    nothing to package in the mock-data view, and the server
                    restricts full-case packages to cooperative_manager, so an
                    enterprise/regulator viewer would only get a 404. The button
                    mirrors that rule; it does not create it. */}
                {mrvCase && role === 'cooperative_manager' ? (
                  <MrvExportPanel caseId={mrvCase.caseId} />
                ) : (
                  <p className="muted" style={{ fontSize: 'var(--fs-caption)' }}>
                    Chỉ quản lý hợp tác xã mới xuất được gói dữ liệu và báo cáo MRV của một hồ sơ thật.
                  </p>
                )}
              </Section>
            </div>
          )
        }}
      </Async>
    </>
  )
}

function StepEvidence({ items }: { items: MrvEvidence[] }) {
  if (items.length === 0) return null
  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: '6px 0 0', display: 'grid', gap: 6 }}>
      {items.map((e) => (
        <li key={e.id} className="chip" style={{ justifyContent: 'space-between', width: '100%' }}>
          <span>
            📎 {e.fileName} <span className="muted">· {e.evidenceType}</span>
          </span>
          <span className="muted" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            {shortHash(e.sha256)} · {date(e.uploadedAt)}
          </span>
        </li>
      ))}
    </ul>
  )
}


const EXPORT_ACTIONS: { format: MrvExportFormat; label: string; working: string; primary?: boolean }[] = [
  { format: 'pdf', label: 'Xuất PDF', working: 'Đang tạo PDF…', primary: true },
  { format: 'xlsx', label: 'Xuất Excel (.xlsx)', working: 'Đang tạo Excel…' },
  { format: 'json', label: 'Xuất JSON', working: 'Đang tạo JSON…' },
]

const CREATE_EXPORT: Record<MrvExportFormat, (caseId: string) => Promise<MrvExportResult>> = {
  json: createMrvJsonExport,
  xlsx: createMrvXlsxExport,
  pdf: createMrvPdfExport,
}

const FORMAT_LABEL: Record<string, string> = { json: 'JSON', xlsx: 'Excel (.xlsx)', pdf: 'PDF' }
const HISTORY_LIMIT = 10

function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  a.click()
  URL.revokeObjectURL(url)
}

/** One export area for the case: generate, download, and see what was made.
 *
 * Every action creates one canonical JSON snapshot on the server; Excel and PDF
 * are rendered from exactly that snapshot, so the three can never disagree.
 * Downloads always go through the verified download route (the server checks
 * the recorded SHA-256 first). The copy says what the files are and are not:
 * support documents, not certification, with evidence binaries not included.
 * History shows metadata only — the API returns no bucket, object path or
 * signed URL to show. */
function MrvExportPanel({ caseId }: { caseId: string }) {
  const [working, setWorking] = useState<MrvExportFormat | null>(null)
  const [status, setStatus] = useState<{ kind: 'done' | 'error'; text: string } | null>(null)
  const history = useAsync(() => listMrvExports(caseId), [caseId])

  async function run(format: MrvExportFormat) {
    setWorking(format)
    setStatus(null)
    try {
      const result = await CREATE_EXPORT[format](caseId)
      saveBlob(await downloadMrvExport(result.exportId), result.fileName)
      const warnings = result.warningCount > 0 ? ` · ${result.warningCount} cảnh báo về dữ liệu chưa đầy đủ` : ''
      setStatus({ kind: 'done', text: `Đã tạo ${FORMAT_LABEL[format]} · SHA-256 tệp ${shortHash(result.fileSha256)}${warnings}` })
      history.reload()
    } catch (error) {
      setStatus({ kind: 'error', text: error instanceof Error ? error.message : 'Không tạo được bản xuất.' })
    } finally {
      setWorking(null)
    }
  }

  async function download(item: MrvExportHistoryItem) {
    setStatus(null)
    try {
      saveBlob(await downloadMrvExport(item.exportId), item.fileName)
    } catch (error) {
      setStatus({ kind: 'error', text: error instanceof Error ? error.message : 'Không tải được tệp.' })
    }
  }

  return (
    <div className="card card--pad">
      <p className="muted" style={{ fontSize: 'var(--fs-caption)' }}>
        Mỗi lần xuất tạo một snapshot dữ liệu gốc (JSON); Excel và PDF được kết xuất từ đúng snapshot đó,
        không tính lại CO₂e hay chỉ số tài nguyên. Đây là tài liệu hỗ trợ, không phải chứng nhận hay kết quả
        thẩm định, và có thể chứa cảnh báo về dữ liệu chưa đầy đủ. Tệp bằng chứng gốc không kèm theo.
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
        {EXPORT_ACTIONS.map((action) => (
          <button
            key={action.format}
            className={action.primary ? 'btn' : 'btn btn--ghost'}
            onClick={() => run(action.format)}
            disabled={working !== null}
            aria-busy={working === action.format}
          >
            {working === action.format ? action.working : action.label}
          </button>
        ))}
      </div>
      {status && (
        <p className="muted" role={status.kind === 'error' ? 'alert' : 'status'} style={{ fontSize: 'var(--fs-caption)', marginTop: 8 }}>
          {status.text}
        </p>
      )}

      <h3 style={{ fontSize: 'var(--fs-sm)', margin: '20px 0 8px' }}>Lịch sử xuất</h3>
      <Async
        state={history}
        skeleton="table"
        isEmpty={(items) => items.length === 0}
        empty={<p className="muted" style={{ fontSize: 'var(--fs-caption)' }}>Chưa có bản xuất nào cho hồ sơ này.</p>}
      >
        {(items) => (
          <>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Định dạng</th>
                    <th>Tạo lúc</th>
                    <th>Người tạo</th>
                    <th>Trạng thái</th>
                    <th>Nguồn dữ liệu</th>
                    <th aria-label="Tải về" />
                  </tr>
                </thead>
                <tbody>
                  {items.slice(0, HISTORY_LIMIT).map((item) => (
                    <tr key={item.exportId}>
                      <td className="col-key">{FORMAT_LABEL[item.format] ?? item.format}</td>
                      <td>{dateTime(item.generatedAt)}</td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{item.generatedBy ? item.generatedBy.slice(0, 8) : '—'}</td>
                      <td><Badge tone="neutral">Đã tạo</Badge></td>
                      <td className="muted">
                        {item.sourceSnapshotExportId ? `Từ snapshot ${item.sourceSnapshotExportId.slice(0, 8)}` : `Snapshot gốc ${item.exportId.slice(0, 8)}`}
                      </td>
                      <td>
                        <button className="btn btn--ghost" onClick={() => download(item)} aria-label={`Tải về ${item.fileName}`}>
                          Tải về
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {items.length > HISTORY_LIMIT && (
              <p className="muted" style={{ fontSize: 'var(--fs-caption)', marginTop: 6 }}>Hiển thị {HISTORY_LIMIT} bản xuất gần nhất.</p>
            )}
          </>
        )}
      </Async>
    </div>
  )
}
