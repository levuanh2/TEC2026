// Central mapping from the frozen error envelope to farmer-facing Vietnamese
// text (brief FW-2 §24). Never surface raw Pydantic/API JSON.
import { ApiError } from '../api/client'

export interface ActivityErrorPresentation {
  message: string
  /** A 5xx/offline/unknown failure did not confirm the write; retry is meaningful. */
  retryable: boolean
}

export function mapActivityError(err: unknown): ActivityErrorPresentation {
  if (!(err instanceof ApiError)) {
    return { message: 'Không thể lưu hoạt động. Dữ liệu chưa được xác nhận là đã lưu.', retryable: true }
  }
  switch (err.code) {
    case 'unauthenticated':
      return { message: 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.', retryable: false }
    case 'not_found':
      return { message: 'Không tìm thấy bản ghi hoặc bạn không còn quyền truy cập.', retryable: false }
    case 'invalid_crop_season_state':
      return { message: 'Vụ này hiện không thể ghi hoạt động (đã đóng hoặc chưa sẵn sàng).', retryable: false }
    case 'duplicate_event':
      return { message: 'Yêu cầu này đã được ghi nhận với dữ liệu khác. Vui lòng tải lại và thử lại.', retryable: false }
    case 'harvested_area_exceeds_plot':
      return { message: err.message || 'Diện tích thu hoạch không được lớn hơn diện tích thửa.', retryable: false }
    case 'validation_error':
      return { message: 'Dữ liệu chưa hợp lệ. Vui lòng kiểm tra lại các trường đã nhập.', retryable: false }
    case 'offline':
      return { message: 'Không thể kết nối máy chủ. Dữ liệu chưa được xác nhận là đã lưu.', retryable: true }
    default:
      if (err.status >= 500 || err.status === 0) {
        return { message: 'Không thể lưu hoạt động. Dữ liệu chưa được xác nhận là đã lưu.', retryable: true }
      }
      return { message: err.message || 'Không thể lưu hoạt động.', retryable: true }
  }
}
