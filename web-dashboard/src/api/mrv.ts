import { apiRequest } from './client'

export interface MrvStep { stepNo: number; name: string; status: string; startedAt: string | null; completedAt: string | null; notes: string | null }
export interface MrvCase { caseId: string; caseCode: string; name: string; periodStart: string; periodEnd: string; status: string; organizationId: string; steps: MrvStep[]; batchCount: number; evidenceCount: number }

type MrvStepResponse = { step_no: number; name: string; status: string; started_at: string | null; completed_at: string | null; notes: string | null }
type MrvCaseResponse = { case_id: string; case_code: string; name: string; period_start: string; period_end: string; status: string; organization_id: string; steps: MrvStepResponse[]; batch_count: number; evidence_count: number }
const mrvCase = (x: MrvCaseResponse): MrvCase => ({ caseId: x.case_id, caseCode: x.case_code, name: x.name, periodStart: x.period_start, periodEnd: x.period_end, status: x.status, organizationId: x.organization_id, steps: x.steps.map(s => ({ stepNo: s.step_no, name: s.name, status: s.status, startedAt: s.started_at, completedAt: s.completed_at, notes: s.notes })), batchCount: x.batch_count, evidenceCount: x.evidence_count })

export async function listMrvCases(): Promise<MrvCase[]> { return (await apiRequest<{ items: MrvCaseResponse[] }>('/v1/mrv/cases')).items.map(mrvCase) }
export async function getMrvCase(id: string): Promise<MrvCase> { return mrvCase(await apiRequest<MrvCaseResponse>(`/v1/mrv/cases/${id}`)) }

export interface MrvEvidence { id: string; stepNo: number; evidenceType: string; fileName: string; mimeType: string; sha256: string | null; uploadedAt: string; productionBatchId: string | null }
export interface MrvBatch { productionBatchId: string; batchCode: string; cropSeasonId: string; farmId: string; plotId: string }

export async function listMrvEvidence(caseId: string): Promise<MrvEvidence[]> {
  const r = await apiRequest<{ items: any[] }>(`/v1/mrv/cases/${caseId}/evidence`)
  return r.items.map((x) => ({ id: x.id, stepNo: x.step_no, evidenceType: x.evidence_type, fileName: x.file_name, mimeType: x.mime_type, sha256: x.sha256 ?? null, uploadedAt: x.uploaded_at, productionBatchId: x.production_batch_id ?? null }))
}
export async function listMrvBatches(caseId: string): Promise<MrvBatch[]> {
  const r = await apiRequest<{ items: any[] }>(`/v1/mrv/cases/${caseId}/batches`)
  return r.items.map((x) => ({ productionBatchId: x.production_batch_id, batchCode: x.batch_code, cropSeasonId: x.crop_season_id, farmId: x.farm_id, plotId: x.plot_id }))
}
