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
    ef_config_path: Path
    # Bộ hệ số phải đã được import vào Supabase với version_code trùng YAML.
    require_factor_set_in_db: bool

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    def require_supabase(self) -> tuple[str, str]:
        if not self.supabase_configured:
            raise ConfigError(
                "Thiếu SUPABASE_URL và/hoặc SUPABASE_SERVICE_ROLE_KEY. "
                "Tạo backend/.env từ .env.example. KHÔNG commit .env."
            )
        return self.supabase_url, self.supabase_service_role_key  # type: ignore[return-value]


def load_settings(dotenv_path: Path | None = None) -> Settings:
    _load_dotenv(dotenv_path or (BACKEND_DIR / ".env"))
    return Settings(
        supabase_url=os.environ.get("SUPABASE_URL") or None,
        supabase_service_role_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or None,
        ef_config_path=Path(os.environ.get("AGRICARBON_EF_CONFIG") or DEFAULT_EF_CONFIG),
        require_factor_set_in_db=os.environ.get("AGRICARBON_REQUIRE_FACTOR_SET_IN_DB", "1")
        != "0",
    )
