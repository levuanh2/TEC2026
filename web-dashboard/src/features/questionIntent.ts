// Deterministic intent HINT for a typed question (no model, no network).
//
// Under D8 strategy B the server answers the intent the client sends; it does not read
// the question to pick a template. Without a hint, a typed "Vụ này còn thiếu dữ liệu gì?"
// stays on the default "explain" radio and gets the explain template. This only
// pre-selects the radio while the user has not chosen one; it is never an authorization
// boundary: the server still refuses "recommend" without Core V1 write authority, and a
// manager is never offered it.
import type { QuestionIntent } from '../api/questions'

/** Lower-case, strip Vietnamese diacritics (đ -> d), collapse spaces. */
export function foldVietnamese(text: string): string {
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'd')
    .toLowerCase().replace(/\s+/g, ' ').trim()
}

// Checked in this order: the first intent with a matching phrase wins.
const RULES: { intent: QuestionIntent; phrases: string[] }[] = [
  { intent: 'data_gap', phrases: ['con thieu', 'thieu du lieu', 'thieu gi', 'dang thieu', 'bi thieu', 'bo sung', 'chua du', 'chua nhap', 'can nhap', 'can ghi', 'du lieu gi'] },
  { intent: 'compare', phrases: ['so sanh', 'so voi', 'vu truoc', 'vu khac', 'chenh lech', 'hon hay kem'] },
  { intent: 'recommend', phrases: ['nen lam', 'lam gi', 'goi y', 'khuyen nghi', 'cach giam', 'lam sao de',
    'lam the nao de', 'co nen'] },
  { intent: 'evidence', phrases: ['tai lieu', 'nguon', 'huong dan', 'quy trinh', 'can cu', 'trich dan', 'quy dinh'] },
  { intent: 'explain', phrases: ['the nao', 'ra sao', 'tom tat', 'giai thich', 'tinh hinh', 'bao nhieu', 'la gi'] },
]

export interface IntentHint {
  intent: QuestionIntent | null
  /** The question asks for an action the audience cannot request (manager). */
  actionNotAvailable: boolean
}

export function suggestIntent(text: string, allowAction: boolean): IntentHint {
  const folded = foldVietnamese(text)
  if (!folded) return { intent: null, actionNotAvailable: false }
  for (const rule of RULES) {
    if (!rule.phrases.some((p) => folded.includes(p))) continue
    if (rule.intent === 'recommend' && !allowAction) return { intent: null, actionNotAvailable: true }
    return { intent: rule.intent, actionNotAvailable: false }
  }
  return { intent: null, actionNotAvailable: false }
}
