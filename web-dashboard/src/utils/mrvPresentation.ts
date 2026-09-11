export type MrvStatus = 'not_started' | 'in_progress' | 'completed' | 'blocked'

const labels: Record<MrvStatus, string> = { not_started: 'Chưa bắt đầu', in_progress: 'Đang thực hiện', completed: 'Hoàn thành', blocked: 'Bị chặn' }
const icons: Record<MrvStatus, string> = { not_started: '○', in_progress: '◐', completed: '✓', blocked: '!' }

export function presentMrvStatus(status: string): { label: string; icon: string; tone: MrvStatus } {
  const tone: MrvStatus = status in labels ? status as MrvStatus : 'not_started'
  return { label: labels[tone], icon: icons[tone], tone }
}

const badgeTone: Record<MrvStatus, 'success' | 'warning' | 'error' | 'neutral'> = {
  completed: 'success', in_progress: 'warning', blocked: 'error', not_started: 'neutral',
}
export const mrvBadgeTone = (status: string): 'success' | 'warning' | 'error' | 'neutral' =>
  badgeTone[status in labels ? (status as MrvStatus) : 'not_started']

/** 6 bước MRV theo QĐ (docs mrv-mapping.md) — dùng khi API chưa trả steps. */
export const MRV_STEP_NAMES = ['Chuẩn bị', 'Đăng ký', 'Thiết lập đường cơ sở', 'Đo đạc', 'Báo cáo', 'Thẩm định']

export function mrvProgress(steps: { status: string }[]): { done: number; inProgress: number; total: number } {
  return {
    done: steps.filter((s) => s.status === 'completed').length,
    inProgress: steps.filter((s) => s.status === 'in_progress').length,
    total: steps.length,
  }
}
