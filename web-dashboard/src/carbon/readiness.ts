/* The one place that decides what a season's Carbon state *means*.
 *
 * Before this module, five screens each re-derived readiness from
 * `/carbon/readiness` in their own way, and they disagreed in front of the
 * user: the Farmer Carbon page named a straw gap and a fuel-factor limit while
 * Management Overview said "đã đủ dữ liệu vụ", the season's Carbon tab offered
 * a "tính lại" button that could only fail, and the Carbon list called the same
 * season "giới hạn hệ số". Same server payload, four stories.
 *
 * Nothing here is methodology. The server already decided which inputs are
 * missing and which flow supplies each one (`backend/carbon/readiness.py`);
 * this module only groups that answer into the five states a human is allowed
 * to see, and picks the single next action each state permits.
 */
import type { CarbonMissingInput, CarbonReadiness, CarbonResult } from '../api/carbon'

/** The five states the UI may show — no screen invents a sixth. */
export type CarbonDisplayState =
  | 'missing_data'          // 1. Thiếu dữ liệu có thể bổ sung
  | 'methodology_limited'   // 2. Giới hạn phương pháp/hệ số
  | 'ready'                 // 3. Sẵn sàng tính
  | 'calculated'            // 4. Đã tính
  | 'stale'                 // 5. Kết quả cũ — cần tính lại
  | 'unknown'               // readiness chưa đọc được (đang tải / lỗi)

export type CarbonActionKind = 'fix_data' | 'calculate' | 'view_result' | 'none'

export interface CarbonNextAction {
  kind: CarbonActionKind
  /** Button/link wording. Never "Sửa ngay" unless data entry can actually fix it. */
  label: string
  /** False when the action exists but cannot succeed right now. */
  enabled: boolean
}

export interface CarbonView {
  /** Blocking inputs a person can still supply. `factor_unavailable` is never here. */
  userFixableGaps: CarbonMissingInput[]
  /** Blocking inputs no data entry resolves — an unverified factor set. */
  methodologyLimitations: CarbonMissingInput[]
  /** Non-blocking: the total still computes, only the per-kg intensity does not. */
  optionalGaps: CarbonMissingInput[]
  calculationStatus: CarbonDisplayState
  /** The calculation would actually run and produce a result. */
  isReady: boolean
  /** A result exists but the inputs or the factor set moved on since. */
  isStale: boolean
  nextAction: CarbonNextAction
  /** Route the next action opens, or null when the action is in-place/none. */
  nextActionTarget: string | null
  /** Short status wording, identical on every screen. */
  label: string
  /** One sentence of why, in plain Vietnamese. */
  detail: string
  /** Semantic tone → the pastel system in tokens.css. Never colour alone. */
  tone: CarbonTone
  icon: CarbonIcon
}

export type CarbonTone = 'attention' | 'methodology' | 'info' | 'positive' | 'neutral'
export type CarbonIcon = 'warning' | 'info' | 'carbon' | 'check' | 'clock'

export interface CarbonViewInput {
  /** `null` while loading or when the read failed — the view says "đang kiểm tra". */
  readiness: CarbonReadiness | null | undefined
  /** The stored calculation, when the season has one. */
  result?: Pick<CarbonResult, 'calculated_at' | 'ef_config_version' | 'input_hash'> | null
  /** For callers that know a result exists but not its record (a metrics
   *  rollup returns the figure, not the calculation). Staleness then stays
   *  unknown, which this module reports as "not stale" rather than guessing. */
  hasResult?: boolean
  /** Latest moment any Carbon input was written, ISO. Optional: absent means
   *  "cannot tell", and this module then never claims a result is stale. */
  latestInputAt?: string | null
  /** The factor-set version the engine runs today (`/health.ef_config_version`). */
  liveEfConfigVersion?: string | null
  /** Where this screen sends someone to supply missing data. */
  fixTarget?: string | null
  /** Where this screen shows the calculation itself. */
  resultTarget?: string | null
}

const blockingOf = (r: CarbonReadiness) => r.missing_inputs.filter((m) => m.blocking)

/** A factor the verified set lacks is a limitation, never a form to fill. */
const isLimitation = (m: CarbonMissingInput) => m.flow === 'factor_unavailable'

/** Did the inputs or the factor set move on after this result was stored?
 *
 * Preferred signal: the server's fingerprint. Readiness carries the
 * `input_hash` the engine would store for an actual calculation of the inputs
 * as they are now; a stored result with a different hash is stale, the same
 * hash is current. Only Carbon inputs are in that hash, so a cost or note edit
 * never makes a result stale, and a recalculation that reuses the stored row
 * (identical inputs) clears it — timestamps got both of those wrong.
 *
 * Fallback, for a server without the fingerprint: a recorded input newer than
 * the calculation, or a factor-set version that no longer matches the engine.
 * When nothing is knowable the answer is "no": a false "cần tính lại" is a lie.
 */
export function isResultStale(input: CarbonViewInput): boolean {
  const live = input.liveEfConfigVersion ?? input.readiness?.ef_config_version ?? null
  const used = input.result?.ef_config_version
  const factorMoved = Boolean(live && used && live !== used)

  const current = input.readiness?.input_hash
  const stored = input.result?.input_hash
  if (current && stored) return current !== stored || factorMoved

  const calculatedAt = input.result?.calculated_at
  if (!calculatedAt) return false
  const calculated = Date.parse(calculatedAt)
  if (Number.isNaN(calculated)) return false

  if (input.latestInputAt) {
    const changed = Date.parse(input.latestInputAt)
    if (!Number.isNaN(changed) && changed > calculated) return true
  }
  return factorMoved
}

const NONE: CarbonNextAction = { kind: 'none', label: '', enabled: false }

/**
 * Group one season's server-reported readiness into the single state every
 * screen renders. Pure: same payload in, same wording out, everywhere.
 */
export function carbonView(input: CarbonViewInput): CarbonView {
  const readiness = input.readiness
  const hasResult = input.hasResult ?? Boolean(input.result?.calculated_at ?? input.result)

  if (!readiness) {
    return {
      userFixableGaps: [], methodologyLimitations: [], optionalGaps: [],
      calculationStatus: 'unknown', isReady: false, isStale: false,
      nextAction: hasResult && input.resultTarget
        ? { kind: 'view_result', label: 'Xem kết quả', enabled: true }
        : NONE,
      nextActionTarget: hasResult ? input.resultTarget ?? null : null,
      label: 'Đang kiểm tra dữ liệu',
      detail: 'Hệ thống đang đọc trạng thái dữ liệu của vụ này.',
      tone: 'neutral', icon: 'clock',
    }
  }

  const blocking = blockingOf(readiness)
  const userFixableGaps = blocking.filter((m) => !isLimitation(m))
  const methodologyLimitations = blocking.filter(isLimitation)
  const optionalGaps = readiness.missing_inputs.filter((m) => !m.blocking)

  // A limitation keeps `can_calculate` false server-side; re-checking it here
  // means a screen can never offer a calculation that is certain to fail.
  const isReady = readiness.can_calculate && methodologyLimitations.length === 0
  const isStale = hasResult && isResultStale(input)

  const calculationStatus: CarbonDisplayState =
    userFixableGaps.length ? 'missing_data'
      : methodologyLimitations.length ? 'methodology_limited'
        : isStale ? 'stale'
          : hasResult ? 'calculated'
            : isReady ? 'ready'
              : 'unknown'

  return {
    userFixableGaps, methodologyLimitations, optionalGaps,
    calculationStatus, isReady, isStale,
    ...presentation(calculationStatus, {
      fixable: userFixableGaps.length,
      limits: methodologyLimitations.length,
      fixTarget: input.fixTarget ?? null,
      resultTarget: input.resultTarget ?? null,
    }),
  }
}

interface PresentArgs { fixable: number; limits: number; fixTarget: string | null; resultTarget: string | null }

function presentation(state: CarbonDisplayState, a: PresentArgs):
Pick<CarbonView, 'label' | 'detail' | 'tone' | 'icon' | 'nextAction' | 'nextActionTarget'> {
  switch (state) {
    case 'missing_data':
      return {
        label: 'Thiếu dữ liệu',
        detail: `Còn ${a.fixable} thông tin cần bổ sung trước khi tính phát thải.`,
        tone: 'attention', icon: 'warning',
        nextAction: { kind: 'fix_data', label: 'Bổ sung dữ liệu', enabled: true },
        nextActionTarget: a.fixTarget,
      }
    case 'methodology_limited':
      return {
        label: 'Giới hạn hệ số',
        // Never "Sửa ngay": there is no form behind this, and saying otherwise
        // sends a farmer looking for a field that does not exist.
        detail: `${a.limits} hạng mục chưa có hệ số phát thải đã xác minh. Không thể bổ sung bằng cách nhập dữ liệu.`,
        tone: 'methodology', icon: 'info',
        nextAction: { kind: 'none', label: '', enabled: false },
        nextActionTarget: null,
      }
    case 'ready':
      return {
        label: 'Sẵn sàng tính',
        detail: 'Đã đủ dữ liệu — có thể tính phát thải cho vụ này.',
        tone: 'info', icon: 'carbon',
        nextAction: { kind: 'calculate', label: 'Tính Carbon', enabled: true },
        nextActionTarget: a.resultTarget,
      }
    case 'calculated':
      return {
        label: 'Đã tính',
        detail: 'Vụ này đã có kết quả phát thải.',
        tone: 'positive', icon: 'check',
        nextAction: a.resultTarget ? { kind: 'view_result', label: 'Xem kết quả', enabled: true } : NONE,
        nextActionTarget: a.resultTarget,
      }
    case 'stale':
      return {
        label: 'Cần tính lại',
        detail: 'Dữ liệu đã thay đổi sau lần tính gần nhất — kết quả đang hiển thị là bản cũ.',
        tone: 'attention', icon: 'clock',
        nextAction: { kind: 'calculate', label: 'Tính lại', enabled: true },
        nextActionTarget: a.resultTarget,
      }
    default:
      return {
        label: 'Chưa xác định',
        detail: 'Chưa đọc được trạng thái dữ liệu của vụ này.',
        tone: 'neutral', icon: 'clock',
        nextAction: NONE, nextActionTarget: null,
      }
  }
}

/** Data completeness, phrased so it can never contradict the Carbon state:
 *  "đủ dữ liệu" is only ever said when no user-fixable gap remains. */
export function dataCompletenessLabel(view: CarbonView): { label: string; tone: CarbonTone } {
  if (view.calculationStatus === 'unknown' && !view.userFixableGaps.length) {
    return { label: 'Đang kiểm tra', tone: 'neutral' }
  }
  if (view.userFixableGaps.length) {
    return { label: `Thiếu ${view.userFixableGaps.length} thông tin`, tone: 'attention' }
  }
  if (view.methodologyLimitations.length) {
    // Data entry *is* complete here, and saying so is true — but the sentence
    // must carry the limitation, or Overview and Carbon disagree again.
    return { label: 'Đủ dữ liệu · vướng hệ số', tone: 'methodology' }
  }
  return { label: 'Đủ dữ liệu', tone: 'positive' }
}
