import type { IconName } from '../icons'
import { label } from '../vocab'

/* MRV status, derived once.
 *
 * The audit caught one case reporting "Chưa bắt đầu", "1/6 bước hoàn thành"
 * and "1 bước đang thực hiện" at the same time. The cause was this file: it
 * held labels for `mrv_step_status` (not_started/in_progress/completed/blocked)
 * and was handed the *case* status (draft/in_progress/ready_for_verification/
 * verified/closed), so `draft` missed the table and fell back to "Chưa bắt đầu"
 * while the steps underneath said otherwise.
 *
 * Now the two are separate: a case's own status is named from the case
 * dictionary, and the progress a human reads is derived from the six steps.
 */

export type MrvStepStatus = 'not_started' | 'in_progress' | 'completed' | 'blocked'

const STEP_ICONS: Record<MrvStepStatus, IconName> = {
  not_started: 'pending', in_progress: 'clock', completed: 'check', blocked: 'blocked',
}
const STEP_TONE: Record<MrvStepStatus, BadgeTone> = {
  completed: 'success', in_progress: 'warning', blocked: 'error', not_started: 'neutral',
}

export type BadgeTone = 'success' | 'warning' | 'error' | 'neutral'

const stepTone = (status: string): MrvStepStatus =>
  (['not_started', 'in_progress', 'completed', 'blocked'] as const).includes(status as MrvStepStatus)
    ? (status as MrvStepStatus)
    : 'not_started'

/** One of the six steps. */
export function presentMrvStep(status: string): { label: string; icon: IconName; tone: MrvStepStatus } {
  const tone = stepTone(status)
  return { label: label('mrvStepStatus', tone), icon: STEP_ICONS[tone], tone }
}

/** The case's own recorded status — "Bản nháp", never "Chưa bắt đầu". */
export function presentMrvCaseStatus(status: string): { label: string; tone: BadgeTone } {
  const tone: BadgeTone =
    status === 'verified' || status === 'closed' ? 'success'
      : status === 'ready_for_verification' ? 'warning'
        : status === 'in_progress' ? 'warning'
          : 'neutral'
  return { label: label('mrvCaseStatus', status), tone }
}

/** 6 bước MRV theo QĐ (docs mrv-mapping.md) — dùng khi API chưa trả steps. */
export const MRV_STEP_NAMES = ['Chuẩn bị', 'Đăng ký', 'Thiết lập đường cơ sở', 'Đo đạc', 'Báo cáo', 'Thẩm định']

export interface MrvProgress { done: number; inProgress: number; blocked: number; total: number }

export function mrvProgress(steps: { status: string }[]): MrvProgress {
  return {
    done: steps.filter((s) => s.status === 'completed').length,
    inProgress: steps.filter((s) => s.status === 'in_progress').length,
    blocked: steps.filter((s) => s.status === 'blocked').length,
    total: steps.length,
  }
}

export type MrvAggregate = 'not_started' | 'in_progress' | 'completed' | 'blocked'

/**
 * The status a person reads, derived from the six steps alone.
 *
 * Rules, in order: a blocked step outranks everything; every step done is
 * "Hoàn thành"; any step started — or any progress at all — is "Đang thực
 * hiện"; nothing started is "Chưa bắt đầu". A case can therefore never show
 * "Chưa bắt đầu" above a step that is under way.
 */
export function mrvAggregateStatus(steps: { status: string }[]): MrvAggregate {
  if (!steps.length) return 'not_started'
  const p = mrvProgress(steps)
  if (p.blocked > 0) return 'blocked'
  if (p.done === p.total) return 'completed'
  if (p.inProgress > 0 || p.done > 0) return 'in_progress'
  return 'not_started'
}

const AGG_ICON: Record<MrvAggregate, IconName> = {
  not_started: 'pending', in_progress: 'clock', completed: 'check', blocked: 'blocked',
}
const AGG_TONE: Record<MrvAggregate, BadgeTone> = {
  not_started: 'neutral', in_progress: 'warning', completed: 'success', blocked: 'error',
}

/** Aggregate status + its wording, icon and tone — what every MRV surface shows. */
export function presentMrvAggregate(steps: { status: string }[]): {
  status: MrvAggregate; label: string; icon: IconName; tone: BadgeTone; progress: MrvProgress
} {
  const status = mrvAggregateStatus(steps)
  return {
    status,
    label: label('mrvStepStatus', status),
    icon: AGG_ICON[status],
    tone: AGG_TONE[status],
    progress: mrvProgress(steps),
  }
}

/** The step a reviewer should look at next, or null when there is none. */
export function currentMrvStep<T extends { status: string; stepNo: number; name: string }>(steps: T[]): T | null {
  return steps.find((s) => s.status === 'in_progress')
    ?? steps.find((s) => s.status === 'blocked')
    ?? steps.find((s) => s.status === 'not_started')
    ?? null
}

export const mrvBadgeTone = (status: string): BadgeTone => STEP_TONE[stepTone(status)]

/** Kept for call sites that legitimately render a single step's status. */
export const presentMrvStatus = presentMrvStep
