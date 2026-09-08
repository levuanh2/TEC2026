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

from typing import Any, Protocol

from .config import Settings


class CropAccessError(Exception):
    """Người gọi không đọc được crop season này qua RLS — hoặc không tồn tại,
    hoặc tồn tại nhưng không thuộc scope của họ. Cố ý không nói rõ cái nào."""


class MissingAuthError(Exception):
    """Thiếu hoặc sai định dạng header Authorization."""


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

    @property
    def client(self) -> Any:
        if self._client is None:
            from supabase import create_client

            url, key = self._settings.require_publishable()
            self._client = create_client(url, key)
        return self._client

    def assert_can_access(self, token: str, crop_season_id: str) -> None:
        # `.auth(token)` gắn JWT vào request PostgREST tiếp theo — PostgREST đọc claim
        # `sub`/`role` từ token đó, tức RLS chạy đúng như thể chính người dùng gọi thẳng
        # Supabase. Không dùng session/refresh — chỉ cần access token hiện có.
        self.client.postgrest.auth(token)
        rows = (
            self.client.table("crop_seasons")
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
