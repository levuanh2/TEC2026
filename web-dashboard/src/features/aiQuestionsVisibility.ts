// Who may SEE the season Q&A panel (V-1b). Kept apart from aiQuestions.tsx so the app shell can
// provide the capability without pulling the panel (and its CSS) into the main chunk.
//
// Visibility is not authorization: the server checks the tier lock, the JWT, the pilot cohort,
// the rate limit and the tenant scope on every question, whatever this file decides.
import { createContext, useContext } from 'react'

/** Build-time switch (default OFF). Read on each call so tests can stub it; Vite inlines it. */
export function aiQuestionsBuildEnabled(): boolean {
  return import.meta.env.VITE_AI_QA_ENABLED === 'true'
}

/** `ai_qa_available` from /v1/me for the CURRENT, verified session (App.tsx provides
 *  `verified && viewer.aiQaAvailable === true`). The default is false, so outside the provider,
 *  while /v1/me is loading or failed, or with a backend that does not send the field, the panel
 *  stays hidden. */
export const AiQuestionsCapability = createContext<boolean>(false)

/** The one rule: build flag on AND the server said true for this session. Anything else hides. */
export function aiQuestionsVisible(buildEnabled: boolean, capability: unknown): boolean {
  return buildEnabled === true && capability === true
}

export function useAiQuestionsVisible(): boolean {
  return aiQuestionsVisible(aiQuestionsBuildEnabled(), useContext(AiQuestionsCapability))
}
