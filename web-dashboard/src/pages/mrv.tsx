import { listMrvCases, getMrvCase, listMrvEvidence, type MrvCase, type MrvEvidence } from '../api/mrv'
import { usingMockData } from '../api/farms'
import { date, shortHash } from '../format'
import { presentMrvStatus, mrvBadgeTone, mrvProgress, MRV_STEP_NAMES } from '../utils/mrvPresentation'
import { Async, Badge, EmptyState, Hero, Notice, PageHead, Progress, Section, useAsync } from '../ui'

type MrvStep = { stepNo: number; name: string; status: string; startedAt: string | null; completedAt: string | null; notes: string | null }

const MOCK_STEPS: MrvStep[] = MRV_STEP_NAMES.map((name, i) => ({
  stepNo: i + 1,
  name,
  status: i === 0 ? 'completed' : i === 1 ? 'in_progress' : 'not_started',
  startedAt: i <= 1 ? '2026-05-02' : null,
  completedAt: i === 0 ? '2026-05-06' : null,
  notes: null,
}))

export function MrvPage() {
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
        empty={<EmptyState icon="📋" title="Chưa có hồ sơ MRV nào trong phạm vi" />}
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
                          {s.status === 'completed' ? '✓' : s.stepNo}
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

              <Section title="Xuất báo cáo" description="Tạo tài liệu PDF/Excel theo 6 bước MRV để nộp cho đơn vị thẩm định">
                <div className="card card--pad" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
                  <div>
                    <b style={{ fontSize: 'var(--fs-sm)' }}>Xuất hồ sơ MRV (PDF/Excel)</b>
                    <p className="muted" style={{ fontSize: 'var(--fs-caption)', marginTop: 3 }}>
                      Chức năng tạo file đang được phát triển — chưa có bản xuất chính thức.
                    </p>
                  </div>
                  <button className="btn btn--ghost" disabled aria-disabled="true">Sắp có</button>
                </div>
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
