/* One Vietnamese sentence for every failure a page can show.
 *
 * Backend and transport messages are written for whoever is on call, not for
 * a cooperative officer or a farmer: "Thiếu header Authorization.", "CV
 * service is not configured", "Failed to fetch". Showing them verbatim makes
 * the product look broken in a way the reader cannot act on, and on the
 * Farmer app it puts English on the screen. Each one is classified here and
 * answered with a sentence that says what happened and what to do next.
 *
 * A message that is already written for a user — Vietnamese prose the API
 * layer produced deliberately — is passed through untouched. */

export type ErrorKind = 'auth' | 'not-found' | 'offline' | 'unavailable' | 'unknown'

const PATTERNS: { kind: ErrorKind; re: RegExp }[] = [
  { kind: 'auth', re: /authorization|unauthor|forbidden|\b401\b|\b403\b|token|đăng nhập lại|phiên đã hết/i },
  { kind: 'not-found', re: /not[_ ]?found|\b404\b|không tìm thấy|phạm vi truy cập/i },
  { kind: 'offline', re: /failed to fetch|networkerror|econnrefused|err_connection|load failed|timeout|timed out|aborted/i },
  { kind: 'unavailable', re: /not configured|unavailable|\b50[0-9]\b|service|upstream|bad gateway/i },
]

export function errorKind(message: string | null | undefined): ErrorKind {
  const m = String(message ?? '')
  return PATTERNS.find((p) => p.re.test(m))?.kind ?? 'unknown'
}

const COPY: Record<ErrorKind, string> = {
  auth: 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại để tiếp tục.',
  'not-found': 'Không tìm thấy dữ liệu, hoặc dữ liệu không thuộc phạm vi truy cập của bạn.',
  offline: 'Không kết nối được máy chủ. Kiểm tra kết nối mạng rồi thử lại.',
  unavailable: 'Tính năng này tạm thời chưa dùng được. Vui lòng thử lại sau.',
  unknown: 'Không tải được dữ liệu. Vui lòng thử lại.',
}

/** True when the message already reads as Vietnamese prose meant for a user. */
export function isUserFacing(message: string | null | undefined): boolean {
  const m = String(message ?? '').trim()
  if (!m) return false
  // Vietnamese-specific letters: no English backend string carries these.
  if (!/[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]/i.test(m)) return false
  return !PATTERNS.some((p) => p.kind !== 'not-found' && p.re.test(m))
}

/** The sentence to put in front of a user for this failure. */
export function friendlyError(message: string | null | undefined): string {
  const kind = errorKind(message)
  if (kind === 'unknown' && isUserFacing(message)) return String(message)
  return COPY[kind]
}

/** Whether retrying can plausibly help — a 401 cannot be retried away. */
export const isRetryable = (message: string | null | undefined) =>
  ['offline', 'unavailable', 'unknown'].includes(errorKind(message))
