// RAG V1 AI Q&A: POST /v1/crop-seasons/{id}/questions (docs/rag/RAG_V1_ARCHITECTURE.md).
// The server decides scope from the JWT, composes or generates the answer, checks every
// citation and number, and renders the values. This file only maps fields: it computes
// nothing, renders no placeholder and never sends an organization/farm/filter field.
import { apiPostNoWrite } from './client'

export type QuestionIntent = 'explain' | 'compare' | 'evidence' | 'data_gap' | 'recommend' | 'what_if'
export type AnswerStatus = 'generated' | 'insufficient_evidence' | 'needs_clarification'

export interface QuestionCitation {
  sourceId: string
  chunkId: string
  documentId: string
  documentVersion: string | null
  title: string
  section: string | null
  sourceType: string
  url: string | null
  publishedAt: string | null
}

export interface TrustedFact {
  factId: string
  kind: string
  value: string | number | boolean | null
  unit: string | null
  source: string
}

export interface AnswerRecommendation {
  title: string
  actions: string[]
  ruleCode: string | null
}

/** A deterministic (M05) recommendation the season already has, as stored. Only action
 *  answers carry them (READ answers never handle recommendation data). */
export interface StoredRecommendation {
  ruleCode: string
  type: string
  title: string | null
  status: string | null
}

export interface QuestionAnswer {
  status: AnswerStatus
  intent: string
  cropSeasonId: string
  answer: string | null
  limitations: string[]
  insufficientReason: string | null
  citations: QuestionCitation[]
  facts: TrustedFact[]
  recommendations: AnswerRecommendation[]
  storedRecommendations: StoredRecommendation[]
  /** 'system_composed' = written by server templates (READ tier, no model);
   *  'model_generated' = written by the configured model (write-tier farmers only). */
  answerSource: 'system_composed' | 'model_generated'
  model: string | null
}

/** Only https links from trusted citation metadata are ever offered to open. */
const safeUrl = (url: unknown): string | null =>
  typeof url === 'string' && /^https:\/\/[^\s]+$/.test(url) ? url : null

export const mapAnswer = (x: any): QuestionAnswer => ({
  status: x.status,
  intent: x.intent,
  cropSeasonId: x.crop_season_id,
  answer: x.answer ?? null,
  limitations: Array.isArray(x.limitations) ? x.limitations : [],
  insufficientReason: x.insufficient_reason ?? null,
  citations: (x.citations ?? []).map((c: any) => ({
    sourceId: c.source_id, chunkId: c.chunk_id, documentId: c.document_id,
    documentVersion: c.document_version ?? null, title: c.title, section: c.section ?? null,
    sourceType: c.source_type, url: safeUrl(c.url), publishedAt: c.published_at ?? null,
  })),
  facts: (x.trusted_facts ?? []).map((f: any) => ({
    factId: f.fact_id, kind: f.kind, value: f.value ?? null, unit: f.unit ?? null, source: f.source,
  })),
  recommendations: (x.recommendations ?? []).map((r: any) => ({
    title: r.title, actions: Array.isArray(r.actions) ? r.actions : [], ruleCode: r.rule_code ?? null,
  })),
  storedRecommendations: (x.signals ?? []).map((s: any) => ({
    ruleCode: s.rule_code, type: s.type, title: s.title ?? null, status: s.status ?? null,
  })),
  answerSource: x.provenance?.answer_source === 'model_generated' ? 'model_generated' : 'system_composed',
  model: x.provenance?.model ?? null,
})

export interface QuestionRequest {
  question: string
  intent: QuestionIntent
  whatIfScenario?: 'awd' | 'continuous_flooding'
}

export async function askSeasonQuestion(cropSeasonId: string, request: QuestionRequest,
                                        signal?: AbortSignal): Promise<QuestionAnswer> {
  const body: Record<string, unknown> = { question: request.question, intent: request.intent }
  if (request.intent === 'what_if') body.what_if_scenario = request.whatIfScenario ?? 'awd'
  return mapAnswer(await apiPostNoWrite<any>(`/v1/crop-seasons/${encodeURIComponent(cropSeasonId)}/questions`,
                                             body, signal))
}
