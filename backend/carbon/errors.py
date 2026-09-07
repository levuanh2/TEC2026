"""Lỗi của Carbon Engine.

Nguyên tắc: thà báo lỗi rõ ràng còn hơn trả một con số trông hợp lý nhưng sai
(SRS NFR-03). Không có fallback, không có giá trị mặc định ngầm.
"""


class CarbonEngineError(Exception):
    """Lỗi gốc của Carbon Engine."""


class ValidationError(CarbonEngineError):
    """Dữ liệu đầu vào không hợp lệ."""


class InvalidWaterRegimeError(ValidationError):
    """Chế độ nước hoặc kịch bản nước không nằm trong danh sách cho phép."""


class ConflictingWaterRegimeError(ValidationError):
    """Một vụ có nhiều bản ghi nước ghi chế độ mâu thuẫn nhau.

    Engine KHÔNG tự chọn một giá trị — người nhập phải sửa dữ liệu.
    """


class MissingActivityDataError(ValidationError):
    """Thiếu dữ liệu hoạt động bắt buộc để tính một nguồn phát thải."""


class MissingEmissionFactorError(CarbonEngineError):
    """Hệ số phát thải cần dùng đang null hoặc không có trong config.

    Đây là trạng thái BÌNH THƯỜNG ở phiên bản hiện tại: toàn bộ hệ số trong
    backend/config/emission_factors.yaml đang là null vì chưa đối chiếu hướng dẫn
    MRV chính thức (open issue OI-02).
    """
