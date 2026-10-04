"""Kiểm tra quyền của người gọi — dùng RLS thật, không tự đoán quyền trong code Python.

Service role bỏ qua RLS hoàn toàn, nên KHÔNG được dùng để quyết định ai thấy gì.
Cách đúng: chạy lại đúng câu SELECT mà PostgREST sẽ chạy cho người dùng đó, bằng chính
JWT của họ và publishable key (không phải service role) — để RLS tự quyết định, giống
hệt như khi Flutter/web gọi thẳng Supabase.

Không phân biệt 403 (không có quyền) với 404 (không tồn tại): nói cho người không có
quyền biết "bản ghi này tồn tại nhưng bạn không xem được" là rò rỉ thông tin về dữ liệu
của nông hộ khác. Cả hai trường hợp đều trả CropAccessError -> 404.
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator, Protocol

from .config import Settings

try:  # gotrue ships with supabase; a fake-client test never needs it
    from supabase_auth.errors import AuthApiError, AuthInvalidJwtError
    _AUTH_REJECTION_ERRORS: tuple[type[BaseException], ...] = (AuthApiError, AuthInvalidJwtError)
except Exception:  # noqa: BLE001 - absence only disables the mapping below
    _AUTH_REJECTION_ERRORS = ()


class CropAccessError(Exception):
    """Người gọi không đọc được crop season này qua RLS — hoặc không tồn tại,
    hoặc tồn tại nhưng không thuộc scope của họ. Cố ý không nói rõ cái nào."""


class MissingAuthError(Exception):
    """Thiếu hoặc sai định dạng header Authorization."""


class InvalidTokenError(Exception):
    """Supabase đã từ chối JWT của người gọi — sai định dạng, sai chữ ký, hoặc hết hạn.

    Khác `MissingAuthError` ở chỗ header ĐÚNG dạng `Bearer <...>`, nên chỉ biết
    token hỏng sau khi Supabase thực sự soi nó. Cả hai đều là 401; tách ra để
    chỗ nào ném lỗi vẫn đọc được ý nghĩa.
    """


# PostgREST gói mọi phán quyết "JWT này không dùng được" vào đúng một mã:
# PGRST301 (thiếu 3 phần, sai chữ ký, hoặc hết hạn). Các mã khác — PGRST116
# không có hàng nào, lỗi schema... — KHÔNG phải phán quyết xác thực.
_JWT_REJECTED_POSTGREST_CODE = "PGRST301"


def _is_rejected_jwt(exc: BaseException) -> bool:
    """Đúng KHI VÀ CHỈ KHI Supabase nói token của người gọi không dùng được.

    Cố ý hẹp. Mất kết nối, Supabase sập, hay lỗi lập trình phải nổi lên thành
    5xx thật: biến chúng thành 401 sẽ đá người dùng về màn hình đăng nhập vì
    một sự cố chẳng liên quan gì tới token của họ, và giấu luôn sự cố thật.
    """
    if getattr(exc, "code", None) == _JWT_REJECTED_POSTGREST_CODE:
        return True
    if _AUTH_REJECTION_ERRORS and isinstance(exc, _AUTH_REJECTION_ERRORS):
        # AuthApiError mang đúng status máy chủ Auth trả về; chỉ 401/403 mới là
        # "token hỏng". AuthRetryableError (mạng) là lớp khác nên không lọt vào.
        return getattr(exc, "status", None) in (401, 403)
    return False


@contextlib.contextmanager
def jwt_rejection_as_invalid_token() -> Iterator[None]:
    """Dịch lời từ chối JWT của Supabase thành `InvalidTokenError`, giữ nguyên mọi lỗi khác."""
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - lọc ngay bên dưới, phần còn lại ném tiếp
        if _is_rejected_jwt(exc):
            raise InvalidTokenError("Token không hợp lệ hoặc đã hết hạn.") from exc
        raise


class CropAccessChecker(Protocol):
    def assert_can_access(self, token: str, crop_season_id: str) -> None: ...


class SupabaseCropAccessChecker:
    """Bản thật: tạo client bằng publishable key, gắn JWT người gọi, thử SELECT.

    RLS của `crop_seasons` (policy `crop_seasons_select`) và của `carbon_calculations`
    (policy `carbon_calculations_select_crop_season`, dùng `private.user_can_read_crop`)
    cùng đi qua một chuỗi Farm -> Plot -> Crop Season như nhau — nên kiểm quyền đọc
    `crop_seasons` là đủ để suy ra quyền đọc carbon của chính season đó.
    """

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    def _client_for(self, token: str) -> Any:
        """Một client GẮN SẴN đúng token này.

        Trước đây checker là singleton và gọi `.auth(token)` trên MỘT client dùng
        chung ngay trước mỗi lần `.execute()`. Hai request song song của hai người
        dùng khác nhau có thể xen kẽ `auth(A) -> auth(B) -> execute(A)`, khiến
        request của A chạy bằng JWT của B — đúng loại rò rỉ chéo tenant mà cả
        module này tồn tại để ngăn. `client_for_token` trả về client theo từng
        token nên không có cửa sổ nào để chuyện đó xảy ra.
        """
        if self._client is not None:  # client do test tiêm vào
            self._client.postgrest.auth(token)
            return self._client
        from .supabase_clients import client_for_token

        return client_for_token(self._settings, token)

    def assert_can_access(self, token: str, crop_season_id: str) -> None:
        # JWT gắn vào client PostgREST — PostgREST đọc claim `sub`/`role` từ token
        # đó, tức RLS chạy đúng như thể chính người dùng gọi thẳng Supabase.
        # Không dùng session/refresh — chỉ cần access token hiện có.
        with jwt_rejection_as_invalid_token():
            rows = (
                self._client_for(token)
                .table("crop_seasons")
                .select("id")
                .eq("id", crop_season_id)
                .execute()
                .data
                or []
            )
        if not rows:
            raise CropAccessError(
                f"'{crop_season_id}' không tồn tại hoặc không thuộc phạm vi truy cập "
                f"của người dùng hiện tại."
            )


def extract_bearer_token(authorization_header: str | None) -> str:
    """Lấy JWT từ header `Authorization: Bearer <token>`. Raise nếu thiếu/sai định dạng."""
    if not authorization_header:
        raise MissingAuthError("Thiếu header Authorization.")
    scheme, _, token = authorization_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise MissingAuthError("Header Authorization phải dạng 'Bearer <token>'.")
    return token


def claims_for_denial_only(token: str) -> dict[str, Any]:
    """The JWT payload WITHOUT verifying the signature -- usable only to REFUSE.

    FastAPI reads `app_metadata.must_change_password` here to answer 403
    `password_change_required` before any work. That is safe only because the
    answer can never widen access: a forged token that drops the flag is still
    rejected by Supabase Auth/PostgREST, and the database checks the live flag
    on auth.users (`private.password_change_pending`). Never use this to allow.
    """
    import base64
    import json

    try:
        payload = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
