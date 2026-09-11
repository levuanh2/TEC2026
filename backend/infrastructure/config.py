"""Cấu hình môi trường cho backend.

Đọc từ biến môi trường / file .env. KHÔNG có giá trị mặc định cho khoá bí mật.
Carbon Engine không đọc file này — engine không biết gì về hạ tầng.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_EF_CONFIG = BACKEND_DIR / "config" / "emission_factors.yaml"


class ConfigError(RuntimeError):
    """Thiếu cấu hình bắt buộc."""


def _load_dotenv(path: Path) -> None:
    """Nạp .env tối giản. Biến môi trường thật luôn thắng file."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None
    supabase_service_role_key: str | None
    # Publishable (anon-equivalent) key. KHÔNG bỏ qua RLS — dùng để replay JWT của người
    # gọi khi kiểm tra quyền đọc/ghi, để PostgREST áp đúng RLS như phía Flutter/web sẽ thấy.
    supabase_publishable_key: str | None
    ef_config_path: Path
    # Bộ hệ số phải đã được import vào Supabase với version_code trùng YAML.
    require_factor_set_in_db: bool
    # Origin trình duyệt được phép gọi API (CORS) — KHÔNG phải secret, không liên
    # quan RLS/auth. Thiếu origin đúng = browser chặn fetch trước khi tới được
    # backend (khác hẳn lỗi 401/403 — request không bao giờ rời trình duyệt).
    cors_origins: list[str]
    # Trusted backend-only Postgres connection. Required by the Farmer Web
    # write repository because one logical activity spans base + detail rows.
    supabase_db_url: str | None = None

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def auth_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_publishable_key)

    def require_supabase(self) -> tuple[str, str]:
        if not self.supabase_configured:
            raise ConfigError(
                "Thiếu SUPABASE_URL và/hoặc SUPABASE_SERVICE_ROLE_KEY. "
                "Tạo backend/.env từ .env.example. KHÔNG commit .env."
            )
        return self.supabase_url, self.supabase_service_role_key  # type: ignore[return-value]

    def require_publishable(self) -> tuple[str, str]:
        if not self.auth_configured:
            raise ConfigError(
                "Thiếu SUPABASE_URL và/hoặc SUPABASE_PUBLISHABLE_KEY — cần để kiểm tra "
                "quyền đọc/ghi theo JWT người gọi (RLS)."
            )
        return self.supabase_url, self.supabase_publishable_key  # type: ignore[return-value]

    def require_db(self) -> str:
        if not self.supabase_db_url:
            raise ConfigError(
                "Thiếu SUPABASE_DB_URL cho activity write transaction. "
                "Chỉ cấu hình ở backend/.env; không đưa vào client."
            )
        return self.supabase_db_url


def load_settings(dotenv_path: Path | None = None) -> Settings:
    _load_dotenv(dotenv_path or (BACKEND_DIR / ".env"))
    return Settings(
        supabase_url=os.environ.get("SUPABASE_URL") or None,
        supabase_service_role_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or None,
        supabase_publishable_key=os.environ.get("SUPABASE_PUBLISHABLE_KEY") or None,
        ef_config_path=Path(os.environ.get("AGRICARBON_EF_CONFIG") or DEFAULT_EF_CONFIG),
        require_factor_set_in_db=os.environ.get("AGRICARBON_REQUIRE_FACTOR_SET_IN_DB", "1")
        != "0",
        cors_origins=[
            origin.strip()
            for origin in os.environ.get(
                "AGRICARBON_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if origin.strip()
        ],
        supabase_db_url=os.environ.get("SUPABASE_DB_URL") or None,
    )
