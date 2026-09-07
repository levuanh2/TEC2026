"""Lỗi của Carbon Engine.

Nguyên tắc: thà báo lỗi rõ ràng còn hơn trả một con số trông hợp lý nhưng sai
(SRS NFR-03). Không fallback, không giá trị mặc định ngầm.
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
    """Hệ số/tham số cần dùng đang null hoặc không có trong config.

    Ví dụ hiện tại: `gwp.ch4` đang PENDING_VERIFICATION nên không quy đổi được
    CH4 sang CO2e (open issue OI-05).
    """


class MethodologyGapError(CarbonEngineError):
    """Phương pháp luận đòi một tham số mà dữ liệu/config chưa biểu diễn được.

    Khác MissingEmissionFactorError ở chỗ: đây là khoảng trống PHƯƠNG PHÁP LUẬN,
    không phải thiếu một con số. Ví dụ: rơm vùi vào đất nhưng không biết vùi trước
    canh tác bao nhiêu ngày — CFOA chênh 5 lần giữa <30 ngày (1,00) và >30 ngày (0,19),
    engine không được đoán.
    """


class DoubleCountingError(CarbonEngineError):
    """Một khối lượng vật chất bị tính vào hai nguồn phát thải cùng lúc."""
