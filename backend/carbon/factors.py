"""Nạp bộ hệ số phát thải từ YAML.

Ràng buộc SRS RB-01: hệ số là DỮ LIỆU, không phải code. Module này là con đường duy
nhất để engine lấy hệ số — không có hằng số phát thải nào viết thẳng trong logic tính.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import MissingEmissionFactorError

# Chỉ trạng thái này mới dùng được cho báo cáo chính thức.
STATUS_VERIFIED = "VERIFIED"

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "emission_factors.yaml"


@dataclass(frozen=True)
class EmissionFactor:
    """Một hệ số phát thải đã nạp, kèm nguồn và trạng thái xác minh."""

    path: str
    value: float
    unit: str | None
    source: str | None
    status: str

    @property
    def is_verified(self) -> bool:
        return self.status == STATUS_VERIFIED


@dataclass(frozen=True)
class EmissionFactorSet:
    """Bộ hệ số của một phiên bản config."""

    version: str
    review_date: str | None
    _factors: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path | None = None) -> EmissionFactorSet:
        config_path = Path(path) if path else DEFAULT_CONFIG_PATH
        with open(config_path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls(
            version=str(raw.get("version", "unknown")),
            review_date=raw.get("review_date"),
            _factors=raw.get("factors") or {},
        )

    def get(self, *path: str) -> EmissionFactor:
        """Lấy một hệ số theo đường dẫn, ví dụ `get("methane", "awd")`.

        Raise MissingEmissionFactorError khi thiếu key hoặc `value` là null —
        KHÔNG bao giờ trả giá trị mặc định (SRS NFR-03).
        """
        dotted = ".".join(path)
        node: Any = self._factors
        for key in path:
            if not isinstance(node, dict) or key not in node:
                raise MissingEmissionFactorError(
                    f"{dotted} không có trong bộ hệ số '{self.version}'."
                )
            node = node[key]

        if not isinstance(node, dict):
            raise MissingEmissionFactorError(f"{dotted} không phải một mục hệ số hợp lệ.")

        value = node.get("value")
        if value is None:
            raise MissingEmissionFactorError(
                f"{dotted} chưa được xác minh/cấu hình "
                f"(status={node.get('status', 'VERIFY')}, "
                f"source={node.get('source', 'chưa có')}). "
                f"Xem open issue OI-02 trong {DEFAULT_CONFIG_PATH.name}."
            )

        return EmissionFactor(
            path=dotted,
            value=float(value),
            unit=node.get("unit"),
            source=node.get("source"),
            status=node.get("status", "VERIFY"),
        )
